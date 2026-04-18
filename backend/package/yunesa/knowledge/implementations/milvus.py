import asyncio
import os
import time
import traceback
from functools import partial
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    WeightedRanker,
    connections,
    db,
    utility,
)

from yunesa import config
from yunesa.knowledge.base import FileStatus, KnowledgeBase
from yunesa.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from yunesa.knowledge.chunking.ragflow_like.presets import resolve_chunk_processing_params
from yunesa.knowledge.utils.kb_utils import get_embedding_config
from yunesa.models.embed import OtherEmbedding
from yunesa.plugins.parser.unified import Parser
from yunesa.utils import hashstr, logger
from yunesa.utils.datetime_utils import utc_isoformat

MILVUS_AVAILABLE = True
CONTENT_SPARSE_FIELD = "content_sparse"
CONTENT_ANALYZER_PARAMS = {"type": "chinese"}


class MilvusKB(KnowledgeBase):
    """ Milvus vector"""

    def __init__(self, work_dir: str, **kwargs):
        """
        initialize Milvus knowledge base

        Args:
            work_dir: directory
            **kwargs: configureparameter
        """
        super().__init__(work_dir)

        if not MILVUS_AVAILABLE:
            raise ImportError("pymilvus is not installed. Please install it with: pip install pymilvus")

        # Milvus configure
        # self.milvus_host = kwargs.get('milvus_host', os.getenv('MILVUS_HOST', 'localhost'))
        # self.milvus_port = kwargs.get('milvus_port', int(os.getenv('MILVUS_PORT', '19530')))
        self.milvus_token = kwargs.get("milvus_token", os.getenv("MILVUS_TOKEN") or "")
        self.milvus_uri = kwargs.get("milvus_uri", os.getenv("MILVUS_URI") or "http://localhost:19530")
        self.milvus_db = kwargs.get("milvus_db") or "yuxi_know"

        # connectname
        self.connection_alias = f"milvus_{hashstr(work_dir, 6)}"

        # storage {db_id: Collection}
        self.collections: dict[str, Any] = {}

        # chunkingconfigure
        self.chunk_size = kwargs.get("chunk_size", 1000)
        self.chunk_overlap = kwargs.get("chunk_overlap", 200)

        # data
        self._metadata_lock = asyncio.Lock()

        # initializeconnect
        self._init_connection()

        logger.info("MilvusKB initialized")

    @property
    def kb_type(self) -> str:
        """knowledge basetype"""
        return "milvus"

    def _init_connection(self):
        """initialize Milvus connect"""
        try:
            # connect Milvus
            connections.connect(alias=self.connection_alias, uri=self.milvus_uri, token=self.milvus_token)

            # createdatabase（does not exist）
            try:
                if self.milvus_db not in db.list_database():
                    db.create_database(self.milvus_db)
                db.using_database(self.milvus_db)
            except Exception as e:
                logger.warning(f"Database operation failed, using default: {e}")

            logger.info(f"Connected to Milvus at {self.milvus_uri}")

        except Exception as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            raise

    async def _create_kb_instance(self, db_id: str, kb_config: dict) -> Any:
        """create Milvus """
        logger.info(f"Creating Milvus collection for {db_id}")

        if not (metadata := self.databases_meta.get(db_id)):
            raise ValueError(f"Database {db_id} not found")

        # getembeddingmodel
        if not (embed_info := metadata.get("embed_info")):
            logger.error(f"Embedding info not found for database {db_id}, using default model")
            embed_info = config.embed_model_names[config.embed_model]

        collection_name = db_id

        try:
            # checkwhether
            if utility.has_collection(collection_name, using=self.connection_alias):
                collection = Collection(name=collection_name, using=self.connection_alias)

                # checkembeddingmodelwhether
                description = collection.description
                expected_model = embed_info["name"] if embed_info else "default"

                if expected_model not in description:
                    logger.warning(
                        f"Collection {collection_name} model mismatch: "
                        f"expected='{expected_model}', found_in_description='{description}'"
                    )
                    utility.drop_collection(collection_name, using=self.connection_alias)
                    return self._create_new_collection(collection_name, embed_info, db_id)

                if not self._collection_supports_bm25(collection):
                    logger.warning(f"Collection {collection_name} schema does not support BM25, recreating")
                    utility.drop_collection(collection_name, using=self.connection_alias)
                    return self._create_new_collection(collection_name, embed_info, db_id)

                logger.info(f"Retrieved existing collection: {collection_name}")
                return collection
            else:
                logger.info(f"Collection {collection_name} not found, creating new one")
                return self._create_new_collection(collection_name, embed_info, db_id)

        except (connections.MilvusException, RuntimeError) as e:
            logger.error(f"Error checking collection {collection_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while managing collection {collection_name}: {e}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
            raise

    def _create_new_collection(self, collection_name: str, embed_info: Any, db_id: str) -> Collection:
        """create Milvus """
        embedding_dim = embed_info.get("dimension", 1024)
        model_name = embed_info.get("name", "default")

        # Schema
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
            FieldSchema(
                name="content",
                dtype=DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params=CONTENT_ANALYZER_PARAMS,
            ),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="file_id", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dim),
            FieldSchema(name=CONTENT_SPARSE_FIELD, dtype=DataType.SPARSE_FLOAT_VECTOR),
        ]
        bm25_function = Function(
            name="content_bm25",
            input_field_names=["content"],
            output_field_names=[CONTENT_SPARSE_FIELD],
            function_type=FunctionType.BM25,
        )

        schema = CollectionSchema(
            fields=fields,
            description=f"Knowledge base collection for {db_id} using {model_name}",
            functions=[bm25_function],
        )

        # create
        collection = Collection(name=collection_name, schema=schema, using=self.connection_alias)

        # createindex
        index_params = {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 1024}}
        collection.create_index("embedding", index_params)
        sparse_index_params = {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
        }
        collection.create_index(CONTENT_SPARSE_FIELD, sparse_index_params)

        logger.info(f"Created new Milvus collection: {collection_name} '{model_name=}', {embedding_dim=}")

        return collection

    def _collection_supports_bm25(self, collection: Collection) -> bool:
        """checkwhether Milvus  BM25  schema。"""
        fields = {field.name: field for field in collection.schema.fields}
        content_field = fields.get("content")
        sparse_field = fields.get(CONTENT_SPARSE_FIELD)
        if not content_field or content_field.dtype != DataType.VARCHAR:
            return False
        if content_field.params.get("enable_analyzer") is not True:
            return False
        if not sparse_field or sparse_field.dtype != DataType.SPARSE_FLOAT_VECTOR:
            return False

        for function in collection.schema.functions:
            if (
                function.type == FunctionType.BM25
                and function.input_field_names == ["content"]
                and function.output_field_names == [CONTENT_SPARSE_FIELD]
            ):
                return True
        return False

    async def _initialize_kb_instance(self, instance: Any) -> None:
        """initialize Milvus （load）"""
        try:
            instance.load()
            logger.info("Milvus collection loaded into memory")
        except Exception as e:
            logger.warning(f"Failed to load collection into memory: {e}")

    def _get_async_embedding(self, embed_info: dict):
        """get embedding """
        # checkwhether model_id ， select_embedding_model
        if embed_info and "model_id" in embed_info:
            from yunesa.models.embed import select_embedding_model

            return select_embedding_model(embed_info["model_id"])

        # （））
        config_dict = get_embedding_config(embed_info)
        return OtherEmbedding(
            model=config_dict.get("model"),
            base_url=config_dict.get("base_url"),
            api_key=config_dict.get("api_key"),
        )

    def _get_async_embedding_function(self, embed_info: dict):
        """get embedding """
        embedding_model = self._get_async_embedding(embed_info)
        batch_size = int(getattr(embedding_model, "batch_size", 40) or 40)
        return partial(embedding_model.abatch_encode, batch_size=batch_size)

    def _get_embedding_function(self, embed_info: dict):
        """get embedding """
        embedding_model = self._get_async_embedding(embed_info)
        batch_size = int(getattr(embedding_model, "batch_size", 40) or 40)
        return partial(embedding_model.batch_encode, batch_size=batch_size)

    async def _get_milvus_collection(self, db_id: str):
        """getcreate Milvus """
        if db_id in self.collections:
            return self.collections[db_id]

        if db_id not in self.databases_meta:
            return None

        try:
            # create
            collection = await self._create_kb_instance(db_id, {})
            await self._initialize_kb_instance(collection)

            self.collections[db_id] = collection
            return collection

        except Exception as e:
            logger.error(f"Failed to create Milvus collection for {db_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _split_text_into_chunks(self, text: str, file_id: str, filename: str, params: dict) -> list[dict]:
        """split"""
        return chunk_markdown(text, file_id, filename, params)

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

        # Get/Create collection
        collection = await self._get_milvus_collection(db_id)
        if not collection:
            raise ValueError(f"Failed to get Milvus collection for {db_id}")

        embed_info = self.databases_meta[db_id].get("embed_info", {})
        embedding_function = self._get_async_embedding_function(embed_info)

        # Get file meta
        async with self._metadata_lock:
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

            # Read processing params inside lock to ensure we get the latest values
            params = resolve_chunk_processing_params(
                kb_additional_params=self.databases_meta.get(db_id, {}).get("metadata"),
                file_processing_params=file_meta.get("processing_params"),
            )
            self.files_meta[file_id]["processing_params"] = params
            await self._save_metadata()
            logger.debug(f"[index_file] file_id={file_id}, processing_params={params}")

        # Add to processing queue
        self._add_to_processing_queue(file_id)

        try:
            # Read markdown
            markdown_content = await self._read_markdown_from_minio(file_meta["markdown_file"])
            filename = file_meta.get("filename")

            # Split
            chunks = self._split_text_into_chunks(markdown_content, file_id, filename, params)
            logger.info(
                f"Split {filename} into {len(chunks)} chunks with params: "
                f"chunk_preset_id={params.get('chunk_preset_id')}, "
                f"chunk_size={params.get('chunk_size')}, "
                f"chunk_overlap={params.get('chunk_overlap')}, "
                f"qa_separator={params.get('qa_separator')}"
            )

            if chunks:
                texts = [chunk["content"] for chunk in chunks]
                embeddings = await embedding_function(texts)

                entities = [
                    [chunk["id"] for chunk in chunks],
                    [chunk["content"] for chunk in chunks],
                    [chunk["source"] for chunk in chunks],
                    [chunk["chunk_id"] for chunk in chunks],
                    [chunk["file_id"] for chunk in chunks],
                    [chunk["chunk_index"] for chunk in chunks],
                    embeddings,
                ]

                # Clean up existing chunks if any (for re-indexing)
                await self.delete_file_chunks_only(db_id, file_id)

                def _insert_records():
                    collection.insert(entities)

                await asyncio.to_thread(_insert_records)

            logger.info(f"Indexed file {file_id} into Milvus")

            # Update status
            async with self._metadata_lock:
                self.files_meta[file_id]["status"] = FileStatus.INDEXED
                self.files_meta[file_id]["updated_at"] = utc_isoformat()
                if operator_id:
                    self.files_meta[file_id]["updated_by"] = operator_id
                await self._persist_file(file_id)
                return self.files_meta[file_id]

        except Exception as e:
            logger.error(f"Indexing failed for {file_id}: {e}")
            async with self._metadata_lock:
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

        collection = await self._get_milvus_collection(db_id)
        if not collection:
            raise ValueError(f"Failed to get Milvus collection for {db_id}")

        embed_info = self.databases_meta[db_id].get("embed_info", {})
        embedding_function = self._get_async_embedding_function(embed_info)

        # processdefaultparameter
        if params is None:
            params = {}
        processed_items_info = []

        for file_id in file_ids:
            # datagetfile
            async with self._metadata_lock:
                if file_id not in self.files_meta:
                    logger.warning(f"File {file_id} not found in metadata, skipping")
                    continue

                file_meta = self.files_meta[file_id]
                file_path = file_meta.get("path")
                filename = file_meta.get("filename")

                if not file_path:
                    logger.warning(f"File path not found for {file_id}, skipping")
                    continue

            # addprocesscolumn
            self._add_to_processing_queue(file_id)

            try:
                # updatestatusprocess
                async with self._metadata_lock:
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

                # delete Milvus data（deletechunks，data）
                await self.delete_file_chunks_only(db_id, file_id)

                # generate chunks
                chunks = self._split_text_into_chunks(markdown_content, file_id, filename, resolved_params)
                logger.info(f"Split {filename} into {len(chunks)} chunks")

                if chunks:
                    texts = [chunk["content"] for chunk in chunks]
                    embeddings = await embedding_function(texts)

                    entities = [
                        [chunk["id"] for chunk in chunks],
                        [chunk["content"] for chunk in chunks],
                        [chunk["source"] for chunk in chunks],
                        [chunk["chunk_id"] for chunk in chunks],
                        [chunk["file_id"] for chunk in chunks],
                        [chunk["chunk_index"] for chunk in chunks],
                        embeddings,
                    ]

                    def _insert_records():
                        collection.insert(entities)

                    await asyncio.to_thread(_insert_records)

                logger.info(f"Updated file {file_path} in Milvus. Done.")

                # updatedatastatus
                async with self._metadata_lock:
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
                logger.error(f"updatefile {file_path} failed: {e}, {traceback.format_exc()}")
                async with self._metadata_lock:
                    self.files_meta[file_id]["status"] = "failed"
                    await self._persist_file(file_id)

                # processcolumnremove
                self._remove_from_processing_queue(file_id)

                # returnfailedfile
                failed_file_meta = file_meta.copy()
                failed_file_meta["status"] = "failed"
                failed_file_meta["file_id"] = file_id
                processed_items_info.append(failed_file_meta)

        return processed_items_info

    def _build_chunk_from_hit(
        self,
        hit: Any,
        score: float,
        include_distances: bool,
        score_field: str | None = None,
    ) -> dict:
        """ Milvus Hit knowledge basereturn Chunk 。"""
        entity = hit.entity
        metadata = {
            "source": entity.get("source", ""),
            "chunk_id": entity.get("chunk_id"),
            "file_id": entity.get("file_id"),
            "chunk_index": entity.get("chunk_index"),
        }
        chunk = {"content": entity.get("content", ""), "metadata": metadata, "score": float(score or 0.0)}
        if score_field:
            chunk[score_field] = float(score or 0.0)
        if include_distances:
            chunk["distance"] = hit.distance
        return chunk

    async def aquery(self, query_text: str, db_id: str, agent_call: bool = False, **kwargs) -> list[dict]:
        """queryknowledge base"""
        collection = await self._get_milvus_collection(db_id)
        if not collection:
            raise ValueError(f"Database {db_id} not found")

        query_params = self._get_query_params(db_id)
        # mergequeryparameter：kwargs（parameter）priority query_params（parameter）
        # usertimesqueryconfigure
        merged_kwargs = {**query_params, **kwargs}

        try:
            # queryparameter（ merged_kwargs read）
            logger.debug(f"Query params: {merged_kwargs}")
            final_top_k = int(merged_kwargs.get("final_top_k", 10))
            final_top_k = max(final_top_k, 1)
            similarity_threshold = float(merged_kwargs.get("similarity_threshold", 0.2))
            metric_type = merged_kwargs.get("metric_type", "COSINE")
            include_distances = bool(merged_kwargs.get("include_distances", True))
            search_mode = str(merged_kwargs.get("search_mode", "vector")).lower()
            if search_mode not in {"vector", "keyword", "hybrid"}:
                search_mode = "vector"

            use_reranker = bool(merged_kwargs.get("use_reranker", False))
            if use_reranker:
                recall_top_k = int(merged_kwargs.get("recall_top_k", 50))
                recall_top_k = max(recall_top_k, final_top_k)
            else:
                recall_top_k = final_top_k

            # buildfiltertable（file）
            file_expr = None
            if file_name := merged_kwargs.get("file_name"):
                safe_file_name = file_name.replace('"', '\\"')
                if "%" not in safe_file_name:
                    file_expr = f'source like "%{safe_file_name}%"'
                else:
                    file_expr = f'source like "{safe_file_name}"'
                logger.debug(f"Using filter expression: {file_expr}")

            output_fields = ["content", "source", "chunk_id", "file_id", "chunk_index"]
            retrieved_chunks: list[dict] = []
            if search_mode == "vector":
                embed_info = self.databases_meta[db_id].get("embed_info", {})
                embedding_function = self._get_embedding_function(embed_info)
                query_embedding = embedding_function([query_text])

                search_params = {"metric_type": metric_type, "params": {"nprobe": 10}}

                results = collection.search(
                    data=query_embedding,
                    anns_field="embedding",
                    param=search_params,
                    limit=recall_top_k,
                    expr=file_expr,
                    output_fields=output_fields,
                )

                if results and len(results) > 0 and len(results[0]) > 0:
                    for hit in results[0]:
                        similarity = hit.distance if metric_type == "COSINE" else 1 / (1 + hit.distance)
                        if similarity < similarity_threshold:
                            continue

                        retrieved_chunks.append(self._build_chunk_from_hit(hit, similarity, include_distances))

                logger.debug(
                    f"Milvus vector query response: {len(retrieved_chunks)} chunks found (after similarity filtering)"
                )

            elif search_mode == "keyword":
                bm25_top_k = int(merged_kwargs.get("bm25_top_k", recall_top_k))
                bm25_top_k = max(bm25_top_k, 1)
                bm25_drop_ratio_search = float(merged_kwargs.get("bm25_drop_ratio_search", 0.0))
                bm25_search_params = {
                    "metric_type": "BM25",
                    "params": {"drop_ratio_search": bm25_drop_ratio_search},
                }

                results = collection.search(
                    data=[query_text],
                    anns_field=CONTENT_SPARSE_FIELD,
                    param=bm25_search_params,
                    limit=bm25_top_k,
                    expr=file_expr,
                    output_fields=output_fields,
                )

                if results and len(results) > 0 and len(results[0]) > 0:
                    for hit in results[0]:
                        retrieved_chunks.append(
                            self._build_chunk_from_hit(hit, hit.distance, include_distances, score_field="bm25_score")
                        )

                logger.debug(f"Milvus BM25 query response: {len(retrieved_chunks)} chunks found")
            else:
                embed_info = self.databases_meta[db_id].get("embed_info", {})
                embedding_function = self._get_embedding_function(embed_info)
                query_embedding = embedding_function([query_text])
                bm25_top_k = int(merged_kwargs.get("bm25_top_k", recall_top_k))
                bm25_top_k = max(bm25_top_k, 1)
                bm25_drop_ratio_search = float(merged_kwargs.get("bm25_drop_ratio_search", 0.0))
                vector_weight = float(merged_kwargs.get("vector_weight", 0.7))
                bm25_weight = float(merged_kwargs.get("bm25_weight", 0.3))

                vector_request = AnnSearchRequest(
                    data=query_embedding,
                    anns_field="embedding",
                    param={"metric_type": metric_type, "params": {"nprobe": 10}},
                    limit=recall_top_k,
                    expr=file_expr,
                )
                bm25_request = AnnSearchRequest(
                    data=[query_text],
                    anns_field=CONTENT_SPARSE_FIELD,
                    param={
                        "metric_type": "BM25",
                        "params": {"drop_ratio_search": bm25_drop_ratio_search},
                    },
                    limit=bm25_top_k,
                    expr=file_expr,
                )
                results = collection.hybrid_search(
                    reqs=[vector_request, bm25_request],
                    rerank=WeightedRanker(vector_weight, bm25_weight),
                    limit=recall_top_k,
                    output_fields=output_fields,
                )
                if results and len(results) > 0 and len(results[0]) > 0:
                    for hit in results[0]:
                        score = float(hit.distance or 0.0)
                        if score < similarity_threshold:
                            continue
                        retrieved_chunks.append(
                            self._build_chunk_from_hit(hit, score, include_distances, score_field="hybrid_score")
                        )

                logger.debug(f"Milvus hybrid query response: {len(retrieved_chunks)} chunks found")

            if not retrieved_chunks:
                return []

            if not use_reranker:
                return retrieved_chunks[:final_top_k]

            # rerankermodel
            reranker_model = merged_kwargs.get("reranker_model")
            if not reranker_model:
                raise ValueError(
                    "Reranker model must be specified when use_reranker=True. "
                    "Please provide reranker_model in query parameters."
                )

            try:
                from yunesa.models.rerank import get_reranker

                reranker = get_reranker(reranker_model)
                try:
                    rerank_start = time.time()
                    documents_text = [chunk["content"] for chunk in retrieved_chunks]
                    rerank_scores = await reranker.acompute_score([query_text, documents_text], normalize=True)

                    for chunk, rerank_score in zip(retrieved_chunks, rerank_scores):
                        chunk["rerank_score"] = float(rerank_score)

                    retrieved_chunks.sort(
                        key=lambda item: item.get("rerank_score", item.get("score", 0.0)), reverse=True
                    )
                    elapsed = time.time() - rerank_start
                    logger.info(f"Reranking completed for {db_id} in {elapsed:.3f}s with model {reranker_model}")
                finally:
                    await reranker.aclose()

            except Exception as exc:  # noqa: BLE001
                logger.error(f"Reranking failed: {exc}, falling back to vector scores")

            # returnresult
            return retrieved_chunks[:final_top_k]

        except Exception as e:
            logger.error(f"Milvus query error: {e}, {traceback.format_exc()}")
            return []

    async def delete_file_chunks_only(self, db_id: str, file_id: str) -> None:
        """deletefilechunksdata，data（updateoperation）"""
        collection = await self._get_milvus_collection(db_id)

        if collection:
            # queryfilewhether，deleteoperation
            try:
                expr = f'file_id == "{file_id}"'
                results = collection.query(expr=expr, output_fields=["id"], limit=1)

                if not results:
                    logger.info(f"File {file_id} not found in Milvus, skipping delete operation")
                else:
                    # fileexecutedelete
                    def _delete_from_milvus():
                        try:
                            collection.delete(expr)
                            logger.info(f"Deleted chunks for file {file_id} from Milvus")
                        except Exception as e:
                            logger.error(f"Error deleting file {file_id} from Milvus: {e}")

                    await asyncio.to_thread(_delete_from_milvus)
            except Exception as e:
                logger.error(f"Error checking file existence in Milvus: {e}")
        # ：delete files_meta[file_id]，dataoperation

    async def delete_file(self, db_id: str, file_id: str) -> None:
        """deletefile（data）"""
        # delete Milvus  chunks data
        await self.delete_file_chunks_only(db_id, file_id)

        # dataoperation
        async with self._metadata_lock:
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

        #  Milvus getchunks
        content_info = {"lines": []}
        collection = await self._get_milvus_collection(db_id)
        if collection:
            try:
                # querydocumentchunks
                expr = f'file_id == "{file_id}"'
                results = collection.query(
                    expr=expr,
                    output_fields=["content", "chunk_id", "chunk_index"],
                    limit=10000,  # file10000chunks
                )

                # buildchunksdata
                doc_chunks = []
                for result in results:
                    chunk_data = {
                        "id": result.get("chunk_id", ""),
                        "content": result.get("content", ""),
                        "chunk_order_index": result.get("chunk_index", 0),
                    }
                    doc_chunks.append(chunk_data)

                #  chunk_order_index sort
                doc_chunks.sort(key=lambda x: x.get("chunk_order_index", 0))
                content_info["lines"] = doc_chunks

            except Exception as e:
                logger.error(f"Failed to get file content from Milvus: {e}")
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

    def delete_database(self, db_id: str) -> dict:
        """deletedatabase，Milvus"""
        # Drop Milvus collection
        try:
            if utility.has_collection(db_id, using=self.connection_alias):
                utility.drop_collection(db_id, using=self.connection_alias)
                logger.info(f"Dropped Milvus collection for {db_id}")
            else:
                logger.info(f"Milvus collection {db_id} does not exist, skipping")
        except Exception as e:
            logger.error(f"Failed to drop Milvus collection {db_id}: {e}")

        # Call base method to delete local files and metadata
        return super().delete_database(db_id)

    def get_query_params_config(self, db_id: str, **kwargs) -> dict:
        """get Milvus knowledge basequeryparameterconfigure"""
        # build Milvus parameter（ reranker_config read）
        options = [
            {
                "key": "search_mode",
                "label": "retrieval",
                "type": "select",
                "default": "vector",
                "options": [
                    {"value": "vector", "label": "vectorretrieval", "description": "vectorretrieval"},
                    {"value": "keyword", "label": "BM25 retrieval", "description": " Milvus BM25 retrieval"},
                    {"value": "hybrid", "label": "retrieval", "description": "Milvus vectorretrieval BM25 retrieval"},
                ],
                "description": "retrieval",
            },
            {
                "key": "final_top_k",
                "label": "return Chunk ",
                "type": "number",
                "default": 10,
                "min": 1,
                "max": 100,
                "description": "rerankerreturndocumentcount",
            },
            {
                "key": "similarity_threshold",
                "label": "threshold（0-1）",
                "type": "number",
                "default": 0.0,
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "description": "filterresult",
            },
            {
                "key": "bm25_top_k",
                "label": "BM25 count",
                "type": "number",
                "default": 50,
                "min": 1,
                "max": 200,
                "description": "BM25 retrievalretrieval BM25 count",
            },
            {
                "key": "vector_weight",
                "label": "vectorretrieval",
                "type": "number",
                "default": 0.7,
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "description": "retrievalvectorresult",
            },
            {
                "key": "bm25_weight",
                "label": "BM25 ",
                "type": "number",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "description": "retrieval BM25 result",
            },
            {
                "key": "bm25_drop_ratio_search",
                "label": "BM25 items",
                "type": "number",
                "default": 0.0,
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "description": "BM25 retrievalitems，retrieval",
            },
            {
                "key": "include_distances",
                "label": "",
                "type": "boolean",
                "default": True,
                "description": "result",
            },
            {
                "key": "metric_type",
                "label": "type",
                "type": "select",
                "default": "COSINE",
                "options": [
                    {"value": "COSINE", "label": "", "description": ""},
                    {"value": "L2", "label": "", "description": "data"},
                    {"value": "IP", "label": "", "description": "vector"},
                ],
                "description": "vectorcalculate",
            },
            {
                "key": "use_reranker",
                "label": "enabledreranker",
                "type": "boolean",
                "default": False,
                "description": "whethermodelretrievalresultrowreranker",
            },
            {
                "key": "reranker_model",
                "label": "rerankermodel",
                "type": "select",
                "default": "",
                "options": [
                    {"label": info.name, "value": model_id}
                    for model_id, info in kwargs.get("reranker_names", {}).items()
                ],
                "description": "timesqueryrerankermodel",
            },
            {
                "key": "recall_top_k",
                "label": "count",
                "type": "number",
                "default": 50,
                "min": 10,
                "max": 200,
                "description": "vectorretrievalretrievalcount（enabledrerankervalid）",
            },
        ]

        return {"type": "milvus", "options": options}

    def __del__(self):
        """clean upconnect"""
        try:
            if hasattr(self, "connection_alias"):
                connections.disconnect(self.connection_alias)
        except Exception:  # noqa: S110
            pass
