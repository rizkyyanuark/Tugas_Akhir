import asyncio
import os
import traceback
from functools import partial

from lightrag import LightRAG, QueryParam
from lightrag.kg.shared_storage import initialize_pipeline_status
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from neo4j import GraphDatabase
from pymilvus import connections, utility

from yunesa import config
from yunesa.knowledge.base import FileStatus, KnowledgeBase
from yunesa.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from yunesa.knowledge.chunking.ragflow_like.presets import resolve_chunk_processing_params
from yunesa.knowledge.utils.kb_utils import get_embedding_config
from yunesa.plugins.parser.unified import Parser
from yunesa.utils import hashstr, logger
from yunesa.utils.datetime_utils import utc_isoformat


class LightRagKB(KnowledgeBase):
    """ LightRAG knowledge base"""

    def __init__(self, work_dir: str, **kwargs):
        """
        initialize LightRAG knowledge base

        Args:
            work_dir: directory
            **kwargs: configureparameter
        """
        super().__init__(work_dir)

        # storage LightRAG  {db_id: LightRAG}
        self.instances: dict[str, LightRAG] = {}
        self._db_write_locks: dict[str, asyncio.Lock] = {}
        self._db_instance_locks: dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

        logger.info("LightRagKB initialized")

    @property
    def kb_type(self) -> str:
        """knowledge basetype"""
        return "lightrag"

    @staticmethod
    def _prepare_lightrag_insert_payload(chunks: list[dict]) -> tuple[str, str | None, bool]:
        if not chunks:
            return "", None, False

        if len(chunks) == 1:
            return chunks[0]["content"], None, False

        delimiter = "\n<|YUNESA_CHUNK_DELIM|>\n"
        payload = delimiter.join(chunk["content"] for chunk in chunks if chunk.get("content"))
        return payload, delimiter, False  #  LightRAG rowtimes，

    def delete_database(self, db_id: str) -> dict:
        """deletedatabase，MilvusNeo4jdata"""
        # Drop Milvus collection
        try:
            milvus_uri = os.getenv("MILVUS_URI") or "http://localhost:19530"
            milvus_token = os.getenv("MILVUS_TOKEN") or ""
            connection_alias = f"lightrag_{hashstr(db_id, 6)}"

            connections.connect(alias=connection_alias, uri=milvus_uri, token=milvus_token)

            # delete LightRAG create
            collection_names = [f"{db_id}_chunks", f"{db_id}_relationships", f"{db_id}_entities"]
            for collection_name in collection_names:
                if utility.has_collection(collection_name, using=connection_alias):
                    utility.drop_collection(collection_name, using=connection_alias)
                    logger.info(f"Dropped Milvus collection {collection_name}")
                else:
                    logger.info(f"Milvus collection {collection_name} does not exist, skipping")

            connections.disconnect(connection_alias)
        except Exception as e:
            logger.error(f"Failed to drop Milvus collection {db_id}: {e}")

        # Delete Neo4j data
        neo4j_uri = os.getenv("NEO4J_URI") or "bolt://localhost:7687"
        neo4j_username = os.getenv("NEO4J_USERNAME") or "neo4j"
        neo4j_password = os.getenv("NEO4J_PASSWORD") or "0123456789"

        try:
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password))
            with driver.session() as session:
                # delete db_id labelnoderelationship
                session.run(
                    """
                    MATCH (n:`"""
                    + db_id
                    + """`)
                    DETACH DELETE n
                """
                )

                logger.info(f"Deleted Neo4j nodes and relationships for workspace {db_id}")
        except Exception as e:
            logger.error(f"Failed to delete Neo4j data for {db_id}: {e}")
        finally:
            if "driver" in locals():
                driver.close()

        # Delete local files and metadata
        return super().delete_database(db_id)

    def update_database(self, db_id: str, name: str, description: str, llm_info: dict = None) -> dict:
        """
        updatedatabaseconfigure

         llm_info ，cache LightRAG ，timesmodelcreate
        """
        if db_id not in self.databases_meta:
            raise ValueError(f"database {db_id} does not exist")

        # check llm_info whether
        old_llm_info = self.databases_meta[db_id].get("llm_info", {})
        llm_info_changed = llm_info is not None and llm_info != old_llm_info
        logger.warning(f"old_llm_info: {old_llm_info}, new_llm_info: {llm_info}, llm_info_changed: {llm_info_changed}")

        # update
        result = super().update_database(db_id, name, description, llm_info)

        #  llm_info ，cache，timesmodel
        if llm_info_changed and db_id in self.instances:
            logger.info(f"LLM model changed, invalidating cached LightRAG instance for {db_id}")
            del self.instances[db_id]

        return result

    async def _create_kb_instance(self, db_id: str, kb_config: dict) -> LightRAG:
        """create LightRAG """
        logger.info(f"Creating LightRAG instance for {db_id}")

        if db_id not in self.databases_meta:
            raise ValueError(f"Database {db_id} not found")

        llm_info = self.databases_meta[db_id].get("llm_info", {})
        embed_info = self.databases_meta[db_id].get("embed_info", {})
        # readcreatedatabaseparameter（）
        metadata = self.databases_meta[db_id].get("metadata", {}) or {}
        addon_params = {}
        if isinstance(metadata.get("addon_params"), dict):
            addon_params.update(metadata.get("addon_params", {}))
        #  metadata  language
        if isinstance(metadata.get("language"), str) and metadata.get("language"):
            addon_params.setdefault("language", metadata.get("language"))
        # defaultenvironmentread，default English
        addon_params.setdefault("language", os.getenv("SUMMARY_LANGUAGE") or "English")

        # createdirectory
        working_dir = os.path.join(self.work_dir, db_id)
        os.makedirs(working_dir, exist_ok=True)

        # create LightRAG 
        rag = LightRAG(
            working_dir=working_dir,
            workspace=db_id,
            llm_model_func=self._get_llm_func(llm_info),
            embedding_func=self._get_embedding_func(embed_info),
            vector_storage="MilvusVectorDBStorage",
            kv_storage="JsonKVStorage",
            graph_storage="Neo4JStorage",
            doc_status_storage="JsonDocStatusStorage",
            log_file_path=os.path.join(working_dir, "lightrag.log"),
            addon_params=addon_params,
        )

        return rag

    async def _initialize_kb_instance(self, instance: LightRAG) -> None:
        """initialize LightRAG """
        logger.info(f"Initializing LightRAG instance for {instance.working_dir}")
        await instance.initialize_storages()
        await initialize_pipeline_status()

    @staticmethod
    async def _ensure_doc_processed(rag: LightRAG, file_id: str) -> None:
        """ LightRAG documentprocesssuccessful，exception。"""
        status_doc = await rag.doc_status.get_by_id(file_id)
        if not status_doc:
            raise ValueError(f"LightRAG documentstatus: {file_id}")

        status = status_doc.get("status")
        status_value = status.value if hasattr(status, "value") else status
        if status_value not in {"processed", "preprocessed"}:
            error_msg = status_doc.get("error_msg") or "unknown error"
            raise ValueError(f"LightRAG entityrelationshipfailed: file_id={file_id}, status={status_value}, error={error_msg}")

    async def _get_lightrag_instance(self, db_id: str) -> LightRAG | None:
        """getcreate LightRAG """
        if db_id in self.instances:
            logger.info(f"Using cached LightRAG instance for {db_id}")
            return self.instances[db_id]

        if db_id not in self.databases_meta:
            return None

        instance_lock = await self._get_db_instance_lock(db_id)
        async with instance_lock:
            if db_id in self.instances:
                logger.info(f"Using cached LightRAG instance for {db_id}")
                return self.instances[db_id]

            try:
                # create
                rag = await self._create_kb_instance(db_id, {})

                # initializestorage
                await self._initialize_kb_instance(rag)

                self.instances[db_id] = rag
                return rag

            except Exception as e:
                logger.error(f"Failed to create LightRAG instance for {db_id}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return None

    async def _get_db_write_lock(self, db_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            return self._db_write_locks.setdefault(db_id, asyncio.Lock())

    async def _get_db_instance_lock(self, db_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            return self._db_instance_locks.setdefault(db_id, asyncio.Lock())

    def _get_llm_func(self, llm_info: dict):
        """get LLM """
        from yunesa.models import select_model

        # userLLM，user；environmentdefault
        if llm_info and llm_info.get("model_spec"):
            model_spec = llm_info["model_spec"]
            logger.info(f"Using user-selected LLM spec: {model_spec}")
        elif llm_info and llm_info.get("provider") and llm_info.get("model_name"):
            model_spec = f"{llm_info['provider']}/{llm_info['model_name']}"
            logger.info(f"Using user-selected LLM: {model_spec}")
        else:
            model_spec = config.default_model
            logger.info(f"Using default LLM from environment: {model_spec}")

        model = select_model(model_spec=model_spec)

        async def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            return await openai_complete_if_cache(
                model=model.model_name,
                prompt=prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=model.api_key,
                base_url=model.base_url,
                **kwargs,
            )

        return llm_model_func

    def _get_embedding_func(self, embed_info: dict):
        """get embedding """
        config_dict = get_embedding_config(embed_info)
        logger.debug(f"Embedding config dict: {config_dict}")

        if config_dict.get("model_id") and config_dict["model_id"].startswith("ollama"):
            from lightrag.llm.ollama import ollama_embed

            from yunesa.utils import get_docker_safe_url

            host = get_docker_safe_url(config_dict["base_url"].replace("/api/embed", ""))
            logger.debug(f"Ollama host: {host}")
            return EmbeddingFunc(
                embedding_dim=config_dict["dimension"],
                max_token_size=8192,
                func=lambda texts: ollama_embed(
                    texts=texts,
                    embed_model=config_dict["name"],
                    api_key=config_dict["api_key"],
                    host=host,
                ),
            )

        # getmodelname，
        if "name" in config_dict and config_dict["name"]:
            model_name = config_dict["name"]
        elif "model" in config_dict and config_dict["model"]:
            model_name = config_dict["model"]
        else:
            raise ValueError(f"Neither 'name' nor 'model' found in config_dict or both are empty: {config_dict}")
        return EmbeddingFunc(
            embedding_dim=config_dict["dimension"],
            max_token_size=8192,
            model_name=model_name,
            func=partial(
                openai_embed.func,
                model=model_name,
                api_key=config_dict["api_key"],
                base_url=config_dict["base_url"].replace("/embeddings", ""),
            ),
        )

    async def index_file(self, db_id: str, file_id: str, operator_id: str | None = None) -> dict:
        """
        Index parsed file (Status: INDEXING -> INDEXED/ERROR_INDEXING)

        Args:
            db_id: Database ID
            file_id: File ID
            operator_id: ID of the user performing the operation

        Returns:
            Updated file metadata
        """
        if db_id not in self.databases_meta:
            raise ValueError(f"Database {db_id} not found")

        db_write_lock = await self._get_db_write_lock(db_id)
        async with db_write_lock:
            rag = await self._get_lightrag_instance(db_id)
            if not rag:
                raise ValueError(f"Failed to get LightRAG instance for {db_id}")

            # Get file meta
            if file_id not in self.files_meta:
                raise ValueError(f"File {file_id} not found")
            file_meta = self.files_meta[file_id]

            # Validate current status - only allow indexing from these states
            current_status = file_meta.get("status")
            allowed_statuses = {
                FileStatus.PARSED,
                FileStatus.ERROR_INDEXING,
                FileStatus.INDEXED,  # For re-indexing
                "done",  # Legacy status
            }

            if current_status not in allowed_statuses:
                raise ValueError(
                    f"Cannot index file with status '{current_status}'. "
                    f"File must be parsed first (status should be one of: {', '.join(allowed_statuses)})"
                )

            # Check markdown file exists
            if not file_meta.get("markdown_file"):
                raise ValueError("File has not been parsed yet (no markdown_file)")

            # Clear previous error if any
            if "error" in file_meta:
                self.files_meta[file_id].pop("error", None)

            # Update status and add to processing queue
            self.files_meta[file_id]["status"] = FileStatus.INDEXING
            self.files_meta[file_id]["updated_at"] = utc_isoformat()
            if operator_id:
                self.files_meta[file_id]["updated_by"] = operator_id
            await self._persist_file(file_id)

            # Add to processing queue
            self._add_to_processing_queue(file_id)

            try:
                # Read markdown
                markdown_content = await self._read_markdown_from_minio(file_meta["markdown_file"])
                file_path = file_meta.get("path")
                filename = file_meta.get("filename") or file_id
                processing_params = resolve_chunk_processing_params(
                    kb_additional_params=self.databases_meta.get(db_id, {}).get("metadata"),
                    file_processing_params=file_meta.get("processing_params"),
                )
                self.files_meta[file_id]["processing_params"] = processing_params
                await self._save_metadata()

                chunks = chunk_markdown(markdown_content, file_id, filename, processing_params)
                chunk_input, split_by_character, split_by_character_only = self._prepare_lightrag_insert_payload(chunks)
                if not chunk_input:
                    chunk_input = markdown_content

                # Clean up existing chunks if any (for re-indexing)
                await self.delete_file_chunks_only(db_id, file_id)

                # Insert
                await rag.ainsert(
                    input=chunk_input,
                    ids=file_id,
                    file_paths=file_path,
                    split_by_character=split_by_character,
                    split_by_character_only=split_by_character_only,
                )
                await self._ensure_doc_processed(rag, file_id)

                logger.info(
                    f"Indexed file {file_id} into LightRAG with {len(chunks)} chunks, "
                    f"chunk_preset_id={processing_params.get('chunk_preset_id')}"
                )

                # Update status
                self.files_meta[file_id]["status"] = FileStatus.INDEXED
                self.files_meta[file_id]["updated_at"] = utc_isoformat()
                if operator_id:
                    self.files_meta[file_id]["updated_by"] = operator_id
                await self._persist_file(file_id)

                return self.files_meta[file_id]

            except Exception as e:
                logger.error(f"Indexing failed for {file_id}: {e}")
                self.files_meta[file_id]["status"] = FileStatus.ERROR_INDEXING
                self.files_meta[file_id]["error"] = str(e)
                self.files_meta[file_id]["updated_at"] = utc_isoformat()
                if operator_id:
                    self.files_meta[file_id]["updated_by"] = operator_id
                await self._persist_file(file_id)
                raise

            finally:
                # Remove from processing queue
                self._remove_from_processing_queue(file_id)

    async def update_content(self, db_id: str, file_ids: list[str], params: dict | None = None) -> list[dict]:
        """updatecontent - file_idsparsefileupdatevector"""
        if db_id not in self.databases_meta:
            raise ValueError(f"Database {db_id} not found")

        db_write_lock = await self._get_db_write_lock(db_id)
        async with db_write_lock:
            rag = await self._get_lightrag_instance(db_id)
            if not rag:
                raise ValueError(f"Failed to get LightRAG instance for {db_id}")

            # processdefaultparameter
            if params is None:
                params = {}
            processed_items_info = []

            for file_id in file_ids:
                # datagetfile
                if file_id not in self.files_meta:
                    logger.warning(f"File {file_id} not found in metadata, skipping")
                    continue

                file_meta = self.files_meta[file_id]
                file_path = file_meta.get("path")

                if not file_path:
                    logger.warning(f"File path not found for {file_id}, skipping")
                    continue

                # addprocesscolumn
                self._add_to_processing_queue(file_id)

                try:
                    # updatestatusprocess
                    resolved_params = resolve_chunk_processing_params(
                        kb_additional_params=self.databases_meta.get(db_id, {}).get("metadata"),
                        file_processing_params=self.files_meta[file_id].get("processing_params"),
                        request_params=params,
                    )
                    self.files_meta[file_id]["processing_params"] = resolved_params
                    self.files_meta[file_id]["status"] = "processing"
                    await self._persist_file(file_id)

                    # parsefile markdown
                    params["image_bucket"] = "public"
                    params["image_prefix"] = f"{db_id}/kb-images"
                    markdown_content = await Parser.aparse(source=file_path, params=params)
                    markdown_content_lines = markdown_content[:100].replace("\n", " ")
                    logger.info(f"Markdown content: {markdown_content_lines}...")
                    filename = file_meta.get("filename") or file_id
                    chunks = chunk_markdown(markdown_content, file_id, filename, resolved_params)
                    chunk_input, split_by_character, split_by_character_only = self._prepare_lightrag_insert_payload(
                        chunks
                    )
                    if not chunk_input:
                        chunk_input = markdown_content

                    # delete LightRAG data（deletechunks，data）
                    await self.delete_file_chunks_only(db_id, file_id)

                    #  LightRAG content
                    await rag.ainsert(
                        input=chunk_input,
                        ids=file_id,
                        file_paths=file_path,
                        split_by_character=split_by_character,
                        split_by_character_only=split_by_character_only,
                    )
                    await self._ensure_doc_processed(rag, file_id)

                    logger.info(f"Updated file {file_path} in LightRAG. Done.")

                    # updatedatastatus
                    self.files_meta[file_id]["status"] = "done"
                    await self._persist_file(file_id)

                    # processcolumnremove
                    self._remove_from_processing_queue(file_id)

                    # returnupdatefile
                    updated_file_meta = file_meta.copy()
                    updated_file_meta["status"] = "done"
                    updated_file_meta["file_id"] = file_id
                    processed_items_info.append(updated_file_meta)

                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"updatefile {file_path} failed: {error_msg}, {traceback.format_exc()}")
                    self.files_meta[file_id]["status"] = "failed"
                    self.files_meta[file_id]["error"] = error_msg
                    await self._persist_file(file_id)

                    # processcolumnremove
                    self._remove_from_processing_queue(file_id)

                    # returnfailedfile
                    failed_file_meta = file_meta.copy()
                    failed_file_meta["status"] = "failed"
                    failed_file_meta["file_id"] = file_id
                    failed_file_meta["error"] = error_msg
                    processed_items_info.append(failed_file_meta)

            return processed_items_info

    async def aquery(self, query_text: str, db_id: str, agent_call: bool = False, **kwargs) -> str:
        """queryknowledge base"""
        rag = await self._get_lightrag_instance(db_id)
        if not rag:
            raise ValueError(f"Database {db_id} not found")

        try:
            # QueryParam parameterlist
            valid_params = {
                "mode",
                "only_need_context",
                "only_need_prompt",
                "response_type",
                "stream",
                "top_k",
                "chunk_top_k",
                "max_entity_tokens",
                "max_relation_tokens",
                "max_total_tokens",
                "hl_keywords",
                "ll_keywords",
                "conversation_history",
                "history_turns",
                "model_func",
                "user_prompt",
                "enable_rerank",
                "include_references",
            }

            # filter kwargs， QueryParam parameter
            query_params = self._get_query_params(db_id)
            query_params = query_params | kwargs
            filtered_kwargs = {k: v for k, v in query_params.items() if k in valid_params}

            # setqueryparameter
            params_dict = {
                "mode": "mix",
                "only_need_context": True,
                "top_k": 10,
            } | filtered_kwargs
            param = QueryParam(**params_dict)

            # Execute query
            response = await rag.aquery_data(query_text, param)
            logger.debug(f"Query response: {str(response)[:1000]}...")

            if agent_call:
                scope = query_params.get("retrieval_content_scope", "chunks")
                data = response.get("data", {}) or {}

                if scope == "chunks":
                    return data.get("chunks", [])

                result = {}
                if scope in ["graph", "all"]:
                    # filter，entityrelationshipcontent
                    exclude_keys = {"source_id", "file_path", "created_at"}

                    ents = data.get("entities", [])
                    rels = data.get("relationships", [])

                    result["entities"] = [{k: v for k, v in e.items() if k not in exclude_keys} for e in ents]
                    result["relationships"] = [{k: v for k, v in r.items() if k not in exclude_keys} for r in rels]
                    result["references"] = data.get("references", [])

                if scope == "all":
                    result["chunks"] = data.get("chunks", [])

                return result

            return response

        except Exception as e:
            logger.error(f"Query error: {e}, {traceback.format_exc()}")
            return ""

    async def delete_file_chunks_only(self, db_id: str, file_id: str) -> None:
        """deletefilechunksdata，data（updateoperation）"""
        rag = await self._get_lightrag_instance(db_id)
        if rag:
            try:
                #  LightRAG deletedocument
                await rag.adelete_by_doc_id(file_id)
                logger.info(f"Deleted chunks for file {file_id} from LightRAG")
            except Exception as e:
                logger.error(f"Error deleting file {file_id} from LightRAG: {e}")
        # ：delete files_meta[file_id]，dataoperation

    async def delete_file(self, db_id: str, file_id: str) -> None:
        """deletefile（data）"""
        # delete LightRAG  chunks data
        await self.delete_file_chunks_only(db_id, file_id)

        # deletefile
        if file_id in self.files_meta:
            del self.files_meta[file_id]
            from yunesa.repositories.knowledge_file_repository import KnowledgeFileRepository

            await KnowledgeFileRepository().delete(file_id)

    async def get_file_basic_info(self, db_id: str, file_id: str) -> dict:
        """getfile（data）"""
        if file_id not in self.files_meta:
            raise Exception(f"File not found: {file_id}")

        return {"meta": self.files_meta[file_id]}

    async def get_file_content(self, db_id: str, file_id: str) -> dict:
        """getfilecontent（chunkslines）"""
        if file_id not in self.files_meta:
            raise Exception(f"File not found: {file_id}")

        #  LightRAG get chunks
        content_info = {"lines": []}
        rag = await self._get_lightrag_instance(db_id)
        if rag:
            try:
                # getdocument chunks
                # LightRAG v1.4+  JsonKVStorage， _data propertydata
                if hasattr(rag.text_chunks, "_data"):
                    all_chunks = dict(rag.text_chunks._data)
                else:
                    logger.warning("text_chunks does not have _data attribute, cannot get file content")
                    return content_info

                # document chunks
                doc_chunks = []
                for chunk_id, chunk_data in all_chunks.items():
                    if isinstance(chunk_data, dict) and chunk_data.get("full_doc_id") == file_id:
                        chunk_data["id"] = chunk_id
                        chunk_data["content_vector"] = []
                        doc_chunks.append(chunk_data)

                #  chunk_order_index sort
                doc_chunks.sort(key=lambda x: x.get("chunk_order_index", 0))
                content_info["lines"] = doc_chunks

            except Exception as e:
                logger.error(f"Failed to get file content from LightRAG: {e}")
                content_info["lines"] = []

        # Try to read markdown content if available
        file_meta = self.files_meta[file_id]
        if file_meta.get("markdown_file"):
            try:
                content = await self._read_markdown_from_minio(file_meta["markdown_file"])
                content_info["content"] = content
            except Exception as e:
                logger.error(f"Failed to read markdown file for {file_id}: {e}")

        return content_info

    async def get_file_info(self, db_id: str, file_id: str) -> dict:
        """getfile（+content）- """
        if file_id not in self.files_meta:
            raise Exception(f"File not found: {file_id}")

        # mergecontent
        basic_info = await self.get_file_basic_info(db_id, file_id)
        content_info = await self.get_file_content(db_id, file_id)

        return {**basic_info, **content_info}

    def get_query_params_config(self, db_id: str, **kwargs) -> dict:
        """get LightRAG knowledge basequeryparameterconfigure"""
        options = [
            {
                "key": "mode",
                "label": "retrieval",
                "type": "select",
                "default": "mix",
                "options": [
                    {"value": "local", "label": "Local", "description": "related"},
                    {"value": "global", "label": "Global", "description": "knowledge"},
                    {"value": "hybrid", "label": "Hybrid", "description": ""},
                    {"value": "naive", "label": "Naive", "description": "search"},
                    {"value": "mix", "label": "Mix", "description": "knowledge graphvectorretrieval"},
                ],
            },
            {
                "key": "only_need_context",
                "label": "",
                "type": "boolean",
                "default": True,
                "description": "return，generateanswer",
            },
            {
                "key": "only_need_prompt",
                "label": "prompt",
                "type": "boolean",
                "default": False,
                "description": "returnprompt，rowretrieval",
            },
            {
                "key": "top_k",
                "label": "TopK",
                "type": "number",
                "default": 10,
                "min": 1,
                "max": 100,
                "description": "returnresultcount",
            },
            {
                "key": "retrieval_content_scope",
                "label": " LLM content",
                "type": "select",
                "default": "chunks",
                "options": [
                    {"value": "chunks", "label": " Chunks", "description": "returndocument"},
                    {"value": "graph", "label": " Entity/Relation", "description": "returnknowledge graph"},
                    {"value": "all", "label": "all", "description": "returndocumentknowledge graph"},
                ],
            },
        ]

        return {"type": "lightrag", "options": options}

    async def export_data(self, db_id: str, format: str = "csv", **kwargs) -> str:
        """
         LightRAG exportknowledge basedata。
        [] disabled。
        """
        # TODO:  LightRAG  Milvus question
        #  aexport_data  "'MilvusVectorDBStorage' object has no attribute 'client_storage'" error。
        #  lightrag question，disabled。
        raise NotImplementedError(" LightRAG  Milvus ，exportunavailable。waiting。")

        # --- enabled ---
        # logger.info(f"Exporting data for db_id {db_id} in format {format} with options {kwargs}")

        # rag = await self._get_lightrag_instance(db_id)
        # if not rag:
        #     raise ValueError(f"Failed to get LightRAG instance for {db_id}")

        # export_dir = os.path.join(self.work_dir, db_id, "exports")
        # os.makedirs(export_dir, exist_ok=True)

        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # output_filename = f"export_{db_id}_{timestamp}.{format}"
        # output_filepath = os.path.join(export_dir, output_filename)

        # include_vectors = kwargs.get('include_vectors', False)

        # #  lightrag export
        # # testtable aexport_data ， to_thread  loop question
        # await rag.aexport_data(
        #     output_path=output_filepath,
        #     file_format=format,
        #     include_vector_data=include_vectors
        # )

        # logger.info(f"Successfully created export file: {output_filepath}")
        # return output_filepath
