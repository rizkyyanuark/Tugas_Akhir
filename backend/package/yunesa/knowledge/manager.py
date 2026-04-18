import asyncio
import os

from yunesa.knowledge.base import KBNotFoundError, KnowledgeBase
from yunesa.knowledge.chunking.ragflow_like.presets import (
    deep_merge,
    ensure_chunk_defaults_in_additional_params,
)
from yunesa.knowledge.factory import KnowledgeBaseFactory
from yunesa.storage.postgres.models_business import User
from yunesa.utils import logger
from yunesa.utils.datetime_utils import utc_isoformat


class KnowledgeBaseManager:
    """
    knowledge basemanager

    managementtypeknowledge base， Repository database，cache。
    """

    def __init__(self, work_dir: str):
        """
        initializeknowledge basemanager

        Args:
            work_dir: directory
        """
        self.work_dir = work_dir
        os.makedirs(work_dir, exist_ok=True)

        # knowledge basecache {kb_type: kb_instance}
        self.kb_instances: dict[str, KnowledgeBase] = {}

        # data
        self._metadata_lock = asyncio.Lock()

    async def initialize(self):
        """initialize"""
        # initializealready existsknowledge base
        self._initialize_existing_kbs()
        logger.info("KnowledgeBaseManager initialized")

    async def _load_all_metadata(self):
        """loaddata - ， KB rowload"""
        pass

    def _initialize_existing_kbs(self):
        """initializealready existsknowledge base"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        async def _async_init():
            kb_repo = KnowledgeBaseRepository()
            rows = await kb_repo.get_all()

            kb_types_in_use = set()
            for row in rows:
                kb_type = row.kb_type or "lightrag"
                kb_types_in_use.add(kb_type)

            logger.info(f"[InitializeKB]  {len(kb_types_in_use)} knowledge basetype: {kb_types_in_use}")

            # knowledge basetypecreateloaddata
            for kb_type in kb_types_in_use:
                try:
                    kb_instance = self._get_or_create_kb_instance(kb_type)
                    #  KB rowloaddata
                    await kb_instance._load_metadata()
                    logger.info(f"[InitializeKB] {kb_type} initialize")
                except Exception as e:
                    logger.error(f"Failed to initialize {kb_type} knowledge base: {e}")
                    import traceback

                    logger.error(traceback.format_exc())

        # rowinitialize
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_init())
        except RuntimeError:
            asyncio.run(_async_init())

    def _get_or_create_kb_instance(self, kb_type: str) -> KnowledgeBase:
        """
        getcreateknowledge base

        Args:
            kb_type: knowledge basetype

        Returns:
            knowledge base
        """
        if kb_type in self.kb_instances:
            return self.kb_instances[kb_type]

        # createknowledge base
        kb_work_dir = os.path.join(self.work_dir, f"{kb_type}_data")
        kb_instance = KnowledgeBaseFactory.create(kb_type, kb_work_dir)

        self.kb_instances[kb_type] = kb_instance
        logger.info(f"Created {kb_type} knowledge base instance")
        return kb_instance

    async def move_file(self, db_id: str, file_id: str, new_parent_id: str | None) -> dict:
        """
        movefile/folder
        """
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.move_file(db_id, file_id, new_parent_id)

    async def _get_kb_for_database(self, db_id: str) -> KnowledgeBase:
        """
        databaseIDgetknowledge base

        Args:
            db_id: databaseID

        Returns:
            knowledge base

        Raises:
            KBNotFoundError: databasedoes not existknowledge basetypenot supported
        """
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)

        if kb is None:
            raise KBNotFoundError(f"Database {db_id} not found")

        kb_type = kb.kb_type or "lightrag"

        if not KnowledgeBaseFactory.is_type_supported(kb_type):
            raise KBNotFoundError(f"Unsupported knowledge base type: {kb_type}")

        return self._get_or_create_kb_instance(kb_type)

    def _get_kb_for_database_sync(self, db_id: str) -> KnowledgeBase:
        """version _get_kb_for_database，"""
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(self._get_kb_for_database(db_id))
        except RuntimeError:
            return asyncio.run(self._get_kb_for_database(db_id))

    # =============================================================================
    # interface -  LightRagBasedKB 
    # =============================================================================

    async def aget_kb(self, db_id: str) -> KnowledgeBase:
        """getknowledge base

        Args:
            db_id: databaseID

        Returns:
            knowledge base
        """
        return await self._get_kb_for_database(db_id)

    def get_kb(self, db_id: str) -> KnowledgeBase:
        """getknowledge base（，）

        Args:
            db_id: databaseID

        Returns:
            knowledge base
        """
        return self._get_kb_for_database_sync(db_id)

    async def get_databases(self) -> dict:
        """getdatabase"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        rows = await kb_repo.get_all()
        all_databases = []
        metadata_reloaded_types: set[str] = set()
        for row in rows:
            kb_type = row.kb_type or "lightrag"
            kb_instance = self._get_or_create_kb_instance(kb_type)
            db_info = kb_instance.get_database_info(row.db_id, include_files=False)
            if not db_info and kb_type not in metadata_reloaded_types:
                try:
                    await kb_instance._load_metadata()
                    metadata_reloaded_types.add(kb_type)
                except Exception as e:
                    logger.warning(f"Failed to reload metadata for kb_type={kb_type}: {e}")
                db_info = kb_instance.get_database_info(row.db_id, include_files=False)

            if not db_info:
                logger.warning(f"Skip database due to missing metadata: db_id={row.db_id}, kb_type={kb_type}")
                continue

            #  share_config  additional_params
            db_info["share_config"] = row.share_config or {"is_shared": True, "accessible_departments": []}
            db_info["additional_params"] = ensure_chunk_defaults_in_additional_params(row.additional_params)
            all_databases.append(db_info)
        return {"databases": all_databases}

    async def check_accessible(self, user: dict, db_id: str) -> bool:
        """checkuserwhetherpermissiondatabase

        Args:
            user: user
            db_id: databaseID

        Returns:
            bool: whetherpermission
        """
        # super admin
        if user.get("role") == "superadmin":
            return True

        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)
        if kb is None:
            return False

        share_config = kb.share_config or {}
        is_shared = share_config.get("is_shared", True)

        # ，permission
        if is_shared:
            return True

        # checkdepartmentpermission
        user_department_id = user.get("department_id")
        accessible_departments = share_config.get("accessible_departments", [])

        if user_department_id is None:
            return False

        # convertrow（character，storage）
        try:
            user_department_id = int(user_department_id)
            accessible_departments = [int(d) for d in accessible_departments]
        except (ValueError, TypeError):
            return False

        return user_department_id in accessible_departments

    async def get_databases_by_raw_id(self, user_id: int) -> dict:
        """userIDgetknowledge baselist（IDversion，interface）"""
        from yunesa.repositories.user_repository import UserRepository

        # databasegetuser
        user_repo = UserRepository()
        user: User | None = await user_repo.get_by_id(id=int(user_id))
        if not user:
            logger.warning(f"User not found: {user_id}")
            return {"databases": []}
        return await self.get_databases_by_user(user)

    async def get_databases_by_user_id(self, user_id: str) -> dict:
        """userIDgetknowledge baselist（characterIDversion）"""
        from yunesa.repositories.user_repository import UserRepository

        # databasegetuser
        user_repo = UserRepository()
        user: User | None = await user_repo.get_by_user_id(user_id)
        if not user:
            logger.warning(f"User not found: {user_id}")
            return {"databases": []}
        return await self.get_databases_by_user(user)

    async def get_databases_by_user(self, user: User | dict) -> dict:
        """userpermissiongetknowledge baselist"""

        # builduser（ User  dict）
        if isinstance(user, dict):
            user_info = user
        else:
            user_info = {
                "role": user.role,
                "department_id": user.department_id,
            }

        user_role = user_info.get("role")
        user_dept = user_info.get("department_id")
        logger.info(f"Getting databases for user with role {user_role} and department {user_dept}")

        all_databases = (await self.get_databases()).get("databases", [])

        # super adminknowledge base
        if user_info.get("role") == "superadmin":
            return {"databases": all_databases}

        filtered_databases = []

        for db in all_databases:
            db_id = db.get("db_id")
            if not db_id:
                continue

            if await self.check_accessible(user_info, db_id):
                filtered_databases.append(db)

        return {"databases": filtered_databases}

    async def database_name_exists(self, database_name: str) -> bool:
        """checkknowledge basenamewhetheralready exists"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository
        from yunesa.storage.postgres.manager import pg_manager

        #  pg_manager initialize
        if not pg_manager._initialized:
            pg_manager.initialize()

        kb_repo = KnowledgeBaseRepository()
        rows = await kb_repo.get_all()
        for row in rows:
            if (row.name or "").lower() == database_name.lower():
                return True
        return False

    async def create_folder(self, db_id: str, folder_name: str, parent_id: str = None) -> dict:
        """Create a folder in the database."""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.create_folder(db_id, folder_name, parent_id)

    async def create_database(
        self,
        database_name: str,
        description: str,
        kb_type: str = "lightrag",
        embed_info: dict | None = None,
        share_config: dict | None = None,
        **kwargs,
    ) -> dict:
        """
        createdatabase

        Args:
            database_name: databasename
            description: databasedescription
            kb_type: knowledge basetype，defaultlightrag
            embed_info: embeddingmodel
            share_config: configure
            **kwargs: configureparameter，chunk_sizechunk_overlap

        Returns:
            database
        """
        if not KnowledgeBaseFactory.is_type_supported(kb_type):
            available_types = list(KnowledgeBaseFactory.get_available_types().keys())
            raise ValueError(f"Unsupported knowledge base type: {kb_type}. Available types: {available_types}")

        # checknamewhetheralready exists
        if await self.database_name_exists(database_name):
            raise ValueError(f"knowledge basename '{database_name}' already exists，name")

        # defaultconfigure
        if share_config is None:
            share_config = {"is_shared": True, "accessible_departments": []}

        kwargs = ensure_chunk_defaults_in_additional_params(kwargs)

        kb_instance = self._get_or_create_kb_instance(kb_type)
        db_info = await kb_instance.create_database(database_name, description, embed_info, **kwargs)
        db_id = db_info["db_id"]

        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        updated = await kb_repo.update(db_id, {"share_config": share_config})
        if updated is None:
            await kb_repo.create(
                {
                    "db_id": db_id,
                    "name": database_name,
                    "description": description,
                    "kb_type": kb_type,
                    "embed_info": embed_info,
                    "llm_info": db_info.get("llm_info"),
                    "additional_params": kwargs.copy(),
                    "share_config": share_config,
                }
            )

        logger.info(f"Created {kb_type} database: {database_name} ({db_id}) with {kwargs}")
        db_info["share_config"] = share_config
        return db_info

    async def delete_database(self, db_id: str) -> dict:
        """deletedatabase"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        try:
            kb_instance = await self._get_kb_for_database(db_id)
            result = await kb_instance.delete_database(db_id)

            # deletedatabase
            kb_repo = KnowledgeBaseRepository()
            await kb_repo.delete(db_id)

            return result
        except KBNotFoundError as e:
            logger.warning(f"Database {db_id} not found during deletion: {e}")
            return {"message": "deletesuccessful"}

    async def add_file_record(
        self, db_id: str, item: str, params: dict | None = None, operator_id: str | None = None
    ) -> dict:
        """Add file record to metadata"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.add_file_record(db_id, item, params, operator_id)

    async def parse_file(self, db_id: str, file_id: str, operator_id: str | None = None) -> dict:
        """Parse file to Markdown"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.parse_file(db_id, file_id, operator_id)

    async def index_file(self, db_id: str, file_id: str, operator_id: str | None = None) -> dict:
        """Index parsed file"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.index_file(db_id, file_id, operator_id)

    async def update_file_params(self, db_id: str, file_id: str, params: dict, operator_id: str | None = None) -> None:
        """Update file processing params"""
        kb_instance = await self._get_kb_for_database(db_id)
        await kb_instance.update_file_params(db_id, file_id, params, operator_id)

    async def aquery(self, query_text: str, db_id: str, **kwargs) -> str:
        """queryknowledge base"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.aquery(query_text, db_id, **kwargs)

    async def export_data(self, db_id: str, format: str = "zip", **kwargs) -> str:
        """exportknowledge basedata"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.export_data(db_id, format=format, **kwargs)

    def query(self, query_text: str, db_id: str, **kwargs) -> str:
        """queryknowledge base（）"""
        kb_instance = self._get_kb_for_database_sync(db_id)
        return kb_instance.query(query_text, db_id, **kwargs)

    async def get_database_info(self, db_id: str) -> dict | None:
        """getdatabase"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)
        if kb is None:
            return None

        try:
            kb_instance = await self._get_kb_for_database(db_id)
            db_info = kb_instance.get_database_info(db_id)
        except KBNotFoundError:
            db_info = {
                "db_id": db_id,
                "name": kb.name,
                "description": kb.description,
                "kb_type": kb.kb_type,
                "files": {},
                "row_count": 0,
                "status": "connect",
            }

        # adddatabase
        db_info["additional_params"] = ensure_chunk_defaults_in_additional_params(kb.additional_params)
        db_info["share_config"] = kb.share_config or {"is_shared": True, "accessible_departments": []}
        db_info["mindmap"] = kb.mindmap
        db_info["sample_questions"] = kb.sample_questions or []
        db_info["query_params"] = kb.query_params

        return db_info

    async def delete_folder(self, db_id: str, folder_id: str) -> None:
        """deletefolder"""
        kb_instance = await self._get_kb_for_database(db_id)
        await kb_instance.delete_folder(db_id, folder_id)

    async def delete_file(self, db_id: str, file_id: str) -> None:
        """deletefile"""
        kb_instance = await self._get_kb_for_database(db_id)
        await kb_instance.delete_file(db_id, file_id)

    async def update_content(self, db_id: str, file_ids: list[str], params: dict | None = None) -> list[dict]:
        """updatecontent（chunking）"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.update_content(db_id, file_ids, params or {})

    async def get_file_basic_info(self, db_id: str, file_id: str) -> dict:
        """getfile（data）"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.get_file_basic_info(db_id, file_id)

    async def get_file_content(self, db_id: str, file_id: str) -> dict:
        """getfilecontent（chunkslines）"""
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.get_file_content(db_id, file_id)

    async def get_file_info(self, db_id: str, file_id: str) -> dict:
        """getfile（+content）- """
        kb_instance = await self._get_kb_for_database(db_id)
        return await kb_instance.get_file_info(db_id, file_id)

    def get_db_upload_path(self, db_id: str | None = None) -> str:
        """getdatabaseuploadpath"""
        if db_id:
            try:
                kb_instance = self._get_kb_for_database_sync(db_id)
                return kb_instance.get_db_upload_path(db_id)
            except KBNotFoundError:
                # databasedoes not exist，createuploadpath
                pass

        # uploadpath
        general_uploads = os.path.join(self.work_dir, "uploads")
        os.makedirs(general_uploads, exist_ok=True)
        return general_uploads

    async def file_name_existed_in_db(self, db_id: str | None, file_name: str | None) -> bool:
        """checkdatabasewhetherfile"""
        if not db_id or not file_name:
            return False
        try:
            kb_instance = await self._get_kb_for_database(db_id)
        except KBNotFoundError:
            return False

        for file_info in kb_instance.files_meta.values():
            if file_info.get("database_id") != db_id:
                continue
            if file_info.get("status") == "failed":
                continue
            if file_info.get("file_name") == file_name:
                return True

        return False

    async def get_same_name_files(self, db_id: str, filename: str) -> list[dict]:
        """getknowledge basefilelist
        file
        return：file、size、uploadtime

        Args:
            db_id: databaseID
            filename: file（file）

        Returns:
            filelist，items：
            - filename: file
            - size: filesize
            - created_at: uploadtime
            - file_id: fileID（download）
        """
        if not db_id or not filename:
            return []
        try:
            kb_instance = await self._get_kb_for_database(db_id)
        except KBNotFoundError:
            return []

        same_name_files = []
        for file_id, file_info in kb_instance.files_meta.items():
            if file_info.get("database_id") != db_id:
                continue
            if file_info.get("status") == "failed":
                continue

            # file（file）
            current_filename = file_info.get("filename", "")

            if current_filename.lower() == filename.lower():
                same_name_files.append(
                    {
                        "file_id": file_id,
                        "filename": current_filename,
                        "size": file_info.get("size", 0),
                        "created_at": file_info.get("created_at", ""),
                        "content_hash": file_info.get("content_hash", ""),
                    }
                )

        # uploadtimesort
        same_name_files.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return same_name_files

    async def file_existed_in_db(self, db_id: str | None, content_hash: str | None) -> bool:
        """checkdatabasewhethercontenthashfile"""
        if not db_id or not content_hash:
            return False

        try:
            kb_instance = await self._get_kb_for_database(db_id)
        except KBNotFoundError:
            return False

        for file_info in kb_instance.files_meta.values():
            if file_info.get("database_id") != db_id:
                continue
            if file_info.get("status") == "failed":
                continue
            if file_info.get("content_hash") == content_hash:
                return True

        return False

    async def update_database(
        self,
        db_id: str,
        name: str,
        description: str,
        llm_info: dict = None,
        additional_params: dict | None = None,
        share_config: dict | None = None,
    ) -> dict:
        """updatedatabase"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)
        if kb is None:
            raise ValueError(f"database {db_id} does not exist")

        kb_instance = await self._get_kb_for_database(db_id)
        kb_instance.update_database(db_id, name, description, llm_info)

        # preparingupdatedata
        update_data: dict = {
            "name": name,
            "description": description,
        }
        if llm_info is not None:
            update_data["llm_info"] = llm_info

        if additional_params is not None:
            merged_additional_params = ensure_chunk_defaults_in_additional_params(
                deep_merge(kb.additional_params or {}, additional_params)
            )
            update_data["additional_params"] = merged_additional_params
            if db_id in kb_instance.databases_meta:
                kb_instance.databases_meta[db_id]["metadata"] = merged_additional_params

        if share_config is not None:
            update_data["share_config"] = share_config

        # savedatabase
        await kb_repo.update(db_id, update_data)

        return await self.get_database_info(db_id)

    def get_retrievers(self) -> dict[str, dict]:
        """getretrieval"""
        all_retrievers = {}

        # knowledge baseretrieval
        for kb_instance in self.kb_instances.values():
            retrievers = kb_instance.get_retrievers()
            all_retrievers.update(retrievers)

        return all_retrievers

    # =============================================================================
    # manager
    # =============================================================================

    def get_supported_kb_types(self) -> dict[str, dict]:
        """getknowledge basetype"""
        return KnowledgeBaseFactory.get_available_types()

    def get_kb_instance_info(self) -> dict[str, dict]:
        """getknowledge base"""
        info = {}
        for kb_type, kb_instance in self.kb_instances.items():
            info[kb_type] = {
                "work_dir": kb_instance.work_dir,
                "database_count": len(kb_instance.databases_meta),
                "file_count": len(kb_instance.files_meta),
            }
        return info

    async def get_statistics(self) -> dict:
        """getstatistics"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository
        from yunesa.repositories.knowledge_file_repository import KnowledgeFileRepository

        kb_repo = KnowledgeBaseRepository()
        rows = await kb_repo.get_all()

        stats = {"total_databases": len(rows), "kb_types": {}, "total_files": 0}

        # knowledge basetypestatistics
        for row in rows:
            kb_type = row.kb_type or "lightrag"
            if kb_type not in stats["kb_types"]:
                stats["kb_types"][kb_type] = 0
            stats["kb_types"][kb_type] += 1

        # statisticsfiletotal
        file_repo = KnowledgeFileRepository()
        files = await file_repo.get_all()
        stats["total_files"] = len(files)

        return stats

    # =============================================================================
    #  -  graph_router.py
    # =============================================================================

    async def _get_lightrag_instance(self, db_id: str):
        """
        get LightRAG （）

        Args:
            db_id: databaseID

        Returns:
            LightRAG ，database lightrag typereturn None

        Raises:
            ValueError: databasedoes not exist lightrag type
        """
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)

        if kb is None:
            logger.error(f"Database {db_id} not found in global metadata")
            return None

        kb_type = kb.kb_type or "lightrag"
        if kb_type != "lightrag":
            logger.error(f"Database {db_id} is not a LightRAG type (actual type: {kb_type})")
            raise ValueError(f"Database {db_id} is not a LightRAG knowledge base")

        kb_instance = await self._get_kb_for_database(db_id)

        if not hasattr(kb_instance, "_get_lightrag_instance"):
            logger.error(f"Knowledge base instance for {db_id} is not LightRagKB")
            return None

        return await kb_instance._get_lightrag_instance(db_id)

    async def is_lightrag_database(self, db_id: str) -> bool:
        """
        checkdatabasewhether LightRAG type

        Args:
            db_id: databaseID

        Returns:
            whether LightRAG typedatabase
        """
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)
        if kb is None:
            return False
        return (kb.kb_type or "lightrag") == "lightrag"

    async def get_lightrag_databases(self) -> list[dict]:
        """
        get LightRAG typedatabase

        Returns:
            LightRAG databaselist
        """
        all_databases = (await self.get_databases())["databases"]
        return [db for db in all_databases if db.get("kb_type", "lightrag") == "lightrag"]

    # =============================================================================
    # data
    # =============================================================================

    async def detect_data_inconsistencies(self) -> dict:
        """
        vectordatabase metadata data

        Returns:
            ，knowledge basetypegroup
        """
        inconsistencies = {
            "milvus": {"missing_collections": [], "missing_files": []},
            "total_missing_collections": 0,
            "total_missing_files": 0,
        }

        logger.info("startvectordatabasedata...")

        #  Milvus data
        if "milvus" in self.kb_instances:
            try:
                milvus_inconsistencies = await self._detect_milvus_inconsistencies()
                inconsistencies["milvus"] = milvus_inconsistencies
                inconsistencies["total_missing_collections"] += len(milvus_inconsistencies["missing_collections"])
                inconsistencies["total_missing_files"] += len(milvus_inconsistencies["missing_files"])
            except Exception as e:
                logger.error(f" Milvus data: {e}")

        # outputresultlog
        self._log_inconsistencies(inconsistencies)

        return inconsistencies

    async def _detect_milvus_inconsistencies(self) -> dict:
        """ Milvus data"""
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        inconsistencies = {"missing_collections": [], "missing_files": []}

        milvus_kb = self.kb_instances["milvus"]

        try:
            from pymilvus import utility

            # get Milvus 
            actual_collection_names = set(utility.list_collections(using=milvus_kb.connection_alias))

            # databasegetdatabaseID
            kb_repo = KnowledgeBaseRepository()
            rows = await kb_repo.get_all()
            all_known_db_ids = {row.db_id for row in rows}

            lightrag_suffixes = ["_chunks", "_relationships", "_entities"]

            #  Milvus  metadata 
            # missing_collections = actual_collection_names - metadata_collection_names
            for collection_name in actual_collection_names:
                # system
                if not collection_name.startswith("kb_"):
                    continue

                # checkwhetherdatabase
                is_known = False

                # 1.  (Milvus typeknowledge base)
                if collection_name in all_known_db_ids:
                    is_known = True
                # 2.  (LightRAG typeknowledge base)
                else:
                    for suffix in lightrag_suffixes:
                        if collection_name.endswith(suffix):
                            potential_db_id = collection_name[: -len(suffix)]
                            if potential_db_id in all_known_db_ids:
                                is_known = True
                                break

                # ，
                if is_known:
                    continue

                # ，
                collection_info = {"collection_name": collection_name, "detected_at": utc_isoformat()}

                # get
                try:
                    from pymilvus import Collection

                    collection = Collection(name=collection_name, using=milvus_kb.connection_alias)
                    collection_info["count"] = collection.num_entities
                    collection_info["description"] = collection.description
                except Exception as e:
                    logger.warning(f"get {collection_name} : {e}")
                    collection_info["count"] = "unknown"

                inconsistencies["missing_collections"].append(collection_info)
                logger.warning(
                    f" Milvus  metadata : {collection_name} "
                    f"(entity: {collection_info['count']})"
                )

            # get metadata databaseID（ Milvus type，checkfile）
            metadata_collection_names = set(milvus_kb.databases_meta.keys())

            # checkfile（database）
            for db_id in metadata_collection_names:
                try:
                    if utility.has_collection(db_id, using=milvus_kb.connection_alias):
                        from pymilvus import Collection

                        collection = Collection(name=db_id, using=milvus_kb.connection_alias)
                        actual_count = collection.num_entities

                        # get metadata filecount
                        metadata_files_count = sum(
                            1 for file_info in milvus_kb.files_meta.values() if file_info.get("database_id") == db_id
                        )

                        # vectordatabasedata metadata file，file
                        if actual_count > 0 and metadata_files_count == 0:
                            inconsistencies["missing_files"].append(
                                {
                                    "database_id": db_id,
                                    "vector_count": actual_count,
                                    "metadata_files_count": metadata_files_count,
                                    "detected_at": utc_isoformat(),
                                }
                            )
                            logger.warning(
                                f"database {db_id}  Milvus  {actual_count} vectordata，"
                                " metadata file"
                            )

                except Exception as e:
                    logger.debug(f"checkdatabase {db_id} file: {e}")

        except Exception as e:
            logger.error(f" Milvus data: {e}")

        return inconsistencies

    def _log_inconsistencies(self, inconsistencies: dict) -> None:
        """resultoutputlog"""
        total_missing_collections = inconsistencies["total_missing_collections"]
        total_missing_files = inconsistencies["total_missing_files"]

        if total_missing_collections == 0 and total_missing_files == 0:
            logger.info("datacompleted，")
            return

        logger.warning("=" * 80)
        logger.warning("datacompleted，：")
        logger.warning("=" * 80)

        # Milvus 
        milvus_missing = inconsistencies["milvus"]["missing_collections"]
        milvus_files_missing = inconsistencies["milvus"]["missing_files"]
        if milvus_missing or milvus_files_missing:
            logger.warning("Milvus ：")
            logger.warning(f"  count: {len(milvus_missing)}")
            for collection_info in milvus_missing:
                logger.warning(f"    - : {collection_info['collection_name']}, entity: {collection_info['count']}")
            logger.warning(f"  filecount: {len(milvus_files_missing)}")
            for file_info in milvus_files_missing:
                logger.warning(
                    f"    - database: {file_info['database_id']}, vector: {file_info['vector_count']}, "
                    f"datafile: {file_info['metadata_files_count']}"
                )

        logger.warning("=" * 80)
        logger.warning(f"： {total_missing_collections} ，file {total_missing_files} ")
        logger.warning("：checkdata，rowdataclean updata")
        logger.warning("=" * 80)

    async def manual_consistency_check(self) -> dict:
        """
        data

        Returns:
            result
        """
        logger.info("data...")
        return await self.detect_data_inconsistencies()
