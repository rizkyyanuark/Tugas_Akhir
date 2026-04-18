import json
import os
import tempfile
import traceback
import warnings
from urllib.parse import urlparse

from yunesa import config
from yunesa.knowledge.graphs.adapters.base import Neo4jConnectionManager
from yunesa.models import select_embedding_model
from yunesa.storage.minio.client import get_minio_client
from yunesa.utils import logger
from yunesa.utils.datetime_utils import utc_isoformat

warnings.filterwarnings("ignore", category=UserWarning)


class UploadGraphService:
    """
    Upload-type graph business logic service
    Handles user file uploads, entity management, vector indexing and other business logic
    """

    def __init__(self, db_manager: Neo4jConnectionManager = None):
        self.connection = db_manager or Neo4jConnectionManager()
        self.files = []
        self.kgdb_name = "neo4j"
        self.embed_model_name = None  # self.load_graph_info() loaded during
        self.embed_model = None  # self.load_graph_info() loaded during
        self.work_dir = os.path.join(
            config.save_dir, "knowledge_graph", self.kgdb_name)
        os.makedirs(self.work_dir, exist_ok=True)
        self.is_initialized_from_file = False

        # Attempt to load saved graph database info
        if not self.load_graph_info():
            logger.debug("Creating new graph database configuration")

    @property
    def driver(self):
        """Get database driver"""
        return self.connection.driver

    @property
    def status(self):
        """Get connection status"""
        return self.connection.status

    def start(self):
        """Start connection"""
        # Neo4jConnectionManager already connects automatically during initialization.
        if not self.connection.is_running():
            self.connection._connect()
            logger.info(
                f"Connected to Neo4j: {self.get_graph_info(self.kgdb_name)}")

    def close(self):
        """Close database connection"""
        self.connection.close()

    def is_running(self):
        """Check if graph database is running"""
        return self.connection.is_running()

    def create_graph_database(self, kgdb_name):
        """Create new database; if it already exists, return existing database name"""
        assert self.driver is not None, "Database is not connected"
        with self.driver.session() as session:
            existing_databases = session.run("SHOW DATABASES")
            existing_db_names = [db["name"] for db in existing_databases]

            if existing_db_names:
                print(f"Database already exists: {existing_db_names[0]}")
                # Return all existing database names
                return existing_db_names[0]

            session.run(f"CREATE DATABASE {kgdb_name}")  # type: ignore
            print(f"Database '{kgdb_name}' created successfully.")
            return kgdb_name  # Return created database name

    def use_database(self, kgdb_name="neo4j"):
        """Switch to specified database"""
        assert kgdb_name == self.kgdb_name, (
            f"Provided database name '{kgdb_name}' does not match current instance database name '{self.kgdb_name}'"
        )
        if self.status == "closed":
            self.start()

    async def jsonl_file_add_entity(self, file_path, kgdb_name="neo4j", embed_model_name=None, batch_size=None):
        """Add entity triples from JSONL file to Neo4j"""
        assert self.driver is not None, "Database is not connected"
        self.connection.status = "processing"
        kgdb_name = kgdb_name or "neo4j"
        self.use_database(kgdb_name)  # Switch to specified database
        logger.info(f"Start adding entity to {kgdb_name} with {file_path}")

        # Detect whether file_path is a URL.
        parsed_url = urlparse(file_path)

        try:
            if parsed_url.scheme in ("http", "https"):  # If it is a URL
                logger.info(
                    f"URL detected, downloading file from MinIO: {file_path}")

                # Using KB approach: parse URL directly and download via internal endpoint (avoid HOST_IP config issues)
                from yunesa.knowledge.utils.kb_utils import parse_minio_url

                bucket_name, object_name = parse_minio_url(file_path)
                minio_client = get_minio_client()

                # Download file content directly
                file_data = await minio_client.adownload_file(bucket_name, object_name)
                logger.info(
                    f"Successfully downloaded file from MinIO: {object_name} ({len(file_data)} bytes)")

                # Create temporary file
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".jsonl", delete=False) as temp_file:
                    temp_file.write(file_data)
                    actual_file_path = temp_file.name

                try:

                    def read_triples(file_path):
                        with open(file_path, encoding="utf-8") as file:
                            for line in file:
                                if line.strip():
                                    yield json.loads(line.strip())

                    triples = list(read_triples(actual_file_path))
                    await self.txt_add_vector_entity(triples, kgdb_name, embed_model_name, batch_size)
                finally:
                    # Clean up temporary file
                    if os.path.exists(actual_file_path):
                        os.unlink(actual_file_path)

            else:
                # Local file path - reject unsafe local paths
                raise ValueError(
                    "Local file paths are not supported; only MinIO URLs are allowed. Please upload the file via the file upload endpoint first.")

        except Exception as e:
            logger.error(f"Failed to process file: {e}")
            raise
        finally:
            self.connection.status = "open"

        # Update and save graph database info
        self.save_graph_info()
        return kgdb_name

    async def txt_add_vector_entity(self, triples, kgdb_name="neo4j", embed_model_name=None, batch_size=None):
        """Add entity triples"""
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        def _index_exists(tx, index_name):
            """Check if index exists"""
            result = tx.run("SHOW INDEXES")
            for record in result:
                if record["name"] == index_name:
                    return True
            return False

        def _parse_node(node_data):
            """Parse node data, return (name, props)"""
            if isinstance(node_data, dict):
                props = node_data.copy()
                name = props.pop("name", "")
                return name, props
            return str(node_data), {}

        def _parse_relation(rel_data):
            """Parse relationship data, return (type, props)"""
            if isinstance(rel_data, dict):
                props = rel_data.copy()
                rel_type = props.pop("type", "")
                return rel_type, props
            return str(rel_data), {}

        def _create_graph(tx, data):
            """Add a single triple"""
            for entry in data:
                h_name, h_props = _parse_node(entry.get("h"))
                t_name, t_props = _parse_node(entry.get("t"))
                r_type, r_props = _parse_relation(entry.get("r"))

                if not h_name or not t_name or not r_type:
                    continue

                tx.run(
                    """
                MERGE (h:Entity:Upload {name: $h_name})
                SET h += $h_props
                MERGE (t:Entity:Upload {name: $t_name})
                SET t += $t_props
                MERGE (h)-[r:RELATION {type: $r_type}]->(t)
                SET r += $r_props
                """,
                    h_name=h_name,
                    h_props=h_props,
                    t_name=t_name,
                    t_props=t_props,
                    r_type=r_type,
                    r_props=r_props,
                )

        def _create_vector_index(tx, dim):
            """Create vector index"""
            # NOTE: Does this rebuild the index repeatedly?
            index_name = "entityEmbeddings"
            if not _index_exists(tx, index_name):
                tx.run(f"""
                CREATE VECTOR INDEX {index_name}
                FOR (n: Entity) ON (n.embedding)
                OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dim},
                `vector.similarity_function`: 'cosine'
                }} }};
                """)

        def _get_nodes_without_embedding(tx, entity_names):
            """Get list of nodes without embeddings"""
            # Build parameter dict by converting list to key-value pairs like "param0", "param1", etc.
            params = {f"param{i}": name for i, name in enumerate(entity_names)}

            if not params:
                return []

            # Build query parameter list
            param_placeholders = ", ".join(
                [f"${key}" for key in params.keys()])

            # Execute query
            result = tx.run(
                f"""
            MATCH (n:Entity)
            WHERE n.name IN [{param_placeholders}] AND n.embedding IS NULL
            RETURN n.name AS name
            """,
                params,
            )

            return [record["name"] for record in result]

        def _batch_set_embeddings(tx, entity_embedding_pairs):
            """Batch set entity embedding vectors"""
            for entity_name, embedding in entity_embedding_pairs:
                tx.run(
                    """
                MATCH (e:Entity {name: $name})
                CALL db.create.setNodeVectorProperty(e, 'embedding', $embedding)
                """,
                    name=entity_name,
                    embedding=embedding,
                )

        # Check if model update is allowed
        if embed_model_name and not self.is_initialized_from_file:
            if embed_model_name != self.embed_model_name:
                logger.info(
                    f"Changing embedding model from {self.embed_model_name} to {embed_model_name}")
                self.embed_model_name = embed_model_name
                self.embed_model = select_embedding_model(
                    self.embed_model_name)

        # Check if model name matches
        if not self.embed_model_name:
            self.embed_model_name = config.embed_model

        cur_embed_info = config.embed_model_names.get(self.embed_model_name)
        logger.warning(
            f"embed_model_name={self.embed_model_name}, {cur_embed_info=}")

        # Allow self.embed_model_name to differ from config.embed_model (user custom selection case)
        # But it must be in the supported model list
        assert self.embed_model_name in config.embed_model_names, f"Unsupported embed model: {self.embed_model_name}"

        with self.driver.session() as session:
            logger.info(f"Adding entity to {kgdb_name}")
            session.execute_write(_create_graph, triples)
            logger.info(
                f"Creating vector index for {kgdb_name} with {config.embed_model}")
            session.execute_write(_create_vector_index, getattr(
                cur_embed_info, "dimension", 1024))

            # Collect all entities that need processing, and de-duplicate.
            all_entities = set()
            for entry in triples:
                h_name, _ = _parse_node(entry.get("h"))
                t_name, _ = _parse_node(entry.get("t"))
                if h_name:
                    all_entities.add(h_name)
                if t_name:
                    all_entities.add(t_name)

            all_entities_list = list(all_entities)

            # Filter nodes that do not have embeddings yet.
            nodes_without_embedding = session.execute_read(
                _get_nodes_without_embedding, all_entities_list)
            if not nodes_without_embedding:
                logger.info(
                    "All entities already have embeddings; no recalculation needed")
                return

            logger.info(
                f"Need to calculate embeddings for {len(nodes_without_embedding)}/{len(all_entities_list)} entities"
            )

            # Process entities in batches.
            # This batch size is mainly limited by memory usage.
            max_batch_size = 1024
            total_entities = len(nodes_without_embedding)

            for i in range(0, total_entities, max_batch_size):
                batch_entities = nodes_without_embedding[i: i + max_batch_size]
                logger.debug(
                    f"Processing entities batch {i // max_batch_size + 1}/"
                    f"{(total_entities - 1) // max_batch_size + 1} ({len(batch_entities)} entities)"
                )

                # Get embedding vectors in batch.
                batch_embeddings = await self.aget_embedding(batch_entities, batch_size=batch_size)

                # Pair each entity name with its embedding vector.
                entity_embedding_pairs = list(
                    zip(batch_entities, batch_embeddings))

                # Write to database in batch.
                session.execute_write(
                    _batch_set_embeddings, entity_embedding_pairs)

            # Save graph info after data ingestion is complete.
            self.save_graph_info()

    async def add_embedding_to_nodes(self, node_names=None, kgdb_name="neo4j", batch_size=None):
        """Add embedding vectors to nodes.

        Args:
            node_names (list, optional): List of node names to embed; None means all nodes without embeddings.
            kgdb_name (str, optional): Graph database name, defaults to 'neo4j'.
            batch_size (int, optional): Embedding batch size.

        Returns:
            int: Number of nodes successfully assigned embeddings.
        """
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        # If node_names is None, fetch all nodes without embeddings.
        if node_names is None:
            node_names = self.query_nodes_without_embedding(kgdb_name)

        count = 0
        with self.driver.session() as session:
            for node_name in node_names:
                try:
                    embedding = await self.aget_embedding(node_name, batch_size=batch_size)
                    session.execute_write(
                        self.set_embedding, node_name, embedding)
                    count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to add embedding vector for node '{node_name}': {e}, {traceback.format_exc()}")

        return count

    def delete_entity(self, entity_name=None, kgdb_name="neo4j"):
        """Delete specific entity triples from database; delete all entities when entity_name is empty."""
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)
        with self.driver.session() as session:
            if entity_name:
                session.execute_write(
                    self._delete_specific_entity, entity_name)
            else:
                session.execute_write(self._delete_all_entities)

    def _delete_specific_entity(self, tx, entity_name):
        query = """
        MATCH (n {name: $entity_name})
        DETACH DELETE n
        """
        tx.run(query, entity_name=entity_name)

    def _delete_all_entities(self, tx):
        query = """
        MATCH (n)
        DETACH DELETE n
        """
        tx.run(query)

    def query_nodes_without_embedding(self, kgdb_name="neo4j"):
        """Query nodes without embedding vectors.

        Returns:
            list: List of nodes without embedding vectors.
        """
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        def query(tx):
            result = tx.run("""
            MATCH (n:Entity)
            WHERE n.embedding IS NULL
            RETURN n.name AS name
            """)
            return [record["name"] for record in result]

        with self.driver.session() as session:
            return session.execute_read(query)

    def get_graph_info(self, graph_name="neo4j"):
        assert self.driver is not None, "Database is not connected"
        self.use_database(graph_name)

        def query(tx):
            # Count only nodes with the Entity label.
            entity_count = tx.run(
                "MATCH (n:Entity) RETURN count(n) AS count").single()["count"]
            # Count only relationships with the RELATION type.
            relationship_count = tx.run(
                "MATCH ()-[r:RELATION]->() RETURN count(r) AS count").single()["count"]
            triples_count = tx.run("MATCH (n:Entity)-[r:RELATION]->(m:Entity) RETURN count(n) AS count").single()[
                "count"
            ]

            # Get all labels
            labels = tx.run(
                "CALL db.labels() YIELD label RETURN collect(label) AS labels").single()["labels"]

            return {
                "graph_name": graph_name,
                "entity_count": entity_count,
                "relationship_count": relationship_count,
                "triples_count": triples_count,
                "labels": labels,
                "status": self.status,
                "embed_model_name": self.embed_model_name,
                "embed_model_configurable": not self.is_initialized_from_file,
                "unindexed_node_count": len(self.query_nodes_without_embedding(graph_name)),
            }

        try:
            if self.is_running():
                # Get database information
                with self.driver.session() as session:
                    graph_info = session.execute_read(query)

                    # Add timestamp
                    graph_info["last_updated"] = utc_isoformat()
                    return graph_info
            else:
                logger.warning(
                    f"Graph database is not connected or not running: {self.status=}")
                return None

        except Exception as e:
            logger.error(
                f"Failed to get graph database info: {e}, {traceback.format_exc()}")
            return None

    def save_graph_info(self, graph_name="neo4j"):
        """
        Save basic graph database info to a JSON file in the working directory.
        Saved fields include database name, status, embedding model name, and others.
        """
        try:
            graph_info = self.get_graph_info(graph_name)
            if graph_info is None:
                logger.error("Graph database info is empty; cannot save")
                return False

            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            with open(info_file_path, "w", encoding="utf-8") as f:
                json.dump(graph_info, f, ensure_ascii=False, indent=2)

            # logger.info(f"Graph database info saved to: {info_file_path}")
            # Mark as initialized from file after successful save (lock config).
            self.is_initialized_from_file = True
            return True
        except Exception as e:
            logger.error(f"Failed to save graph database info: {e}")
            return False

    def load_graph_info(self):
        """
        Load basic graph database info from JSON file in the working directory.
        Returns True when loading succeeds, otherwise False.
        """
        try:
            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            if not os.path.exists(info_file_path):
                logger.debug(
                    f"Graph database info file does not exist: {info_file_path}")
                return False

            with open(info_file_path, encoding="utf-8") as f:
                graph_info = json.load(f)

            # Update object properties
            if graph_info.get("embed_model_name"):
                self.embed_model_name = graph_info["embed_model_name"]

            # Re-select embedding model
            if self.embed_model_name:
                self.embed_model = select_embedding_model(
                    self.embed_model_name)

            # Load more fields here if needed.
            # Note: self.kgdb_name is not updated here because it is set during initialization.

            self.is_initialized_from_file = True
            logger.info(
                f"Graph database info loaded; last update time: {graph_info.get('last_updated')}")
            return True
        except Exception as e:
            logger.error(f"Failed to load graph database info: {e}")
            return False

    def _resolve_embedding_batch_size(self, batch_size=None):
        if batch_size is not None:
            return batch_size
        return int(getattr(self.embed_model, "batch_size", 40) or 40)

    async def aget_embedding(self, text, batch_size=None):
        if isinstance(text, list):
            resolved_batch_size = self._resolve_embedding_batch_size(
                batch_size)
            outputs = await self.embed_model.abatch_encode(text, batch_size=resolved_batch_size)
            return outputs
        else:
            outputs = await self.embed_model.aencode(text)
            return outputs

    def get_embedding(self, text, batch_size=None):
        if isinstance(text, list):
            resolved_batch_size = self._resolve_embedding_batch_size(
                batch_size)
            outputs = self.embed_model.batch_encode(
                text, batch_size=resolved_batch_size)
            return outputs
        else:
            outputs = self.embed_model.encode([text])[0]
            return outputs

    def set_embedding(self, tx, entity_name, embedding):
        """Set embedding vector for a single entity."""
        tx.run(
            """
        MATCH (e:Entity {name: $name})
        CALL db.create.setNodeVectorProperty(e, 'embedding', $embedding)
        """,
            name=entity_name,
            embedding=embedding,
        )

    def query_node(
        self, keyword, threshold=0.9, kgdb_name="neo4j", hops=2, max_entities=8, return_format="graph", **kwargs
    ):
        """Entry point for querying nodes in the knowledge graph."""
        assert self.driver is not None, "Database is not connected"
        assert self.is_running(), "Graph database is not started"

        self.use_database(kgdb_name)

        # Simple whitespace tokenization with OR-style aggregation.
        tokens = [t for t in str(keyword).split(" ") if t]
        if not tokens:
            tokens = [str(keyword)]

        # Aggregate name -> score; accumulate vector scores, fuzzy matches get light weight.
        entity_to_score = {}
        for token in tokens:
            # Query using vector index
            results_sim = self._query_with_vector_sim(
                token, kgdb_name, threshold)
            for r in results_sim:
                name = r[0]  # Keep consistent [0] indexing for name extraction
                score = 0.0
                try:
                    # neo4j.Record supports key access
                    score = float(r["score"])
                except Exception:
                    # Fallback: assign a base score if score retrieval fails.
                    score = 0.5
                entity_to_score[name] = max(
                    entity_to_score.get(name, 0.0), score)

            # Fuzzy query (case-insensitive); matched entities get a smaller score.
            results_fuzzy = self._query_with_fuzzy_match(token, kgdb_name)
            for fr in results_fuzzy:
                # _query_with_fuzzy_match returns values() in shape [name]
                name = fr[0]
                # Give light weight to avoid overriding higher vector scores.
                entity_to_score[name] = max(
                    entity_to_score.get(name, 0.0), 0.3)

        # Sort and truncate
        sorted_entity_to_score = sorted(
            entity_to_score.items(), key=lambda x: x[1], reverse=True)
        qualified_entities = [name for name,
                              _ in sorted_entity_to_score][:max_entities]

        logger.debug(f"Graph Query Entities: {keyword}, {qualified_entities=}")

        # Query each qualified entity
        all_query_results = {"nodes": [], "edges": [], "triples": []}
        for entity in qualified_entities:
            query_result = self._query_specific_entity(
                entity_name=entity, kgdb_name=kgdb_name, hops=hops)
            if return_format == "graph":
                all_query_results["nodes"].extend(query_result["nodes"])
                all_query_results["edges"].extend(query_result["edges"])
            elif return_format == "triples":
                all_query_results["triples"].extend(query_result["triples"])
            else:
                raise ValueError(f"Invalid return_format: {return_format}")

        # Basic deduplication
        if return_format == "graph":
            seen_node_ids = set()
            dedup_nodes = []
            for n in all_query_results["nodes"]:
                nid = n.get("id") if isinstance(n, dict) else n
                if nid not in seen_node_ids:
                    seen_node_ids.add(nid)
                    dedup_nodes.append(n)
            all_query_results["nodes"] = dedup_nodes

            seen_edges = set()
            dedup_edges = []
            for e in all_query_results["edges"]:
                key = (e.get("source_id"), e.get("target_id"), e.get("type"))
                if key not in seen_edges:
                    seen_edges.add(key)
                    dedup_edges.append(e)
            all_query_results["edges"] = dedup_edges

        elif return_format == "triples":
            seen_triples = set()
            dedup_triples = []
            for t in all_query_results["triples"]:
                if t not in seen_triples:
                    seen_triples.add(t)
                    dedup_triples.append(t)
            all_query_results["triples"] = dedup_triples

        return all_query_results

    def _query_with_fuzzy_match(self, keyword, kgdb_name="neo4j"):
        """Fuzzy query."""
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        def query_fuzzy_match(tx, keyword):
            result = tx.run(
                """
            MATCH (n:Upload)
            WHERE toLower(n.name) CONTAINS toLower($keyword)
            RETURN DISTINCT n.name AS name
            """,
                keyword=keyword,
            )
            values = result.values()
            logger.debug(f"Fuzzy Query Results: {values}")
            return values

        with self.driver.session() as session:
            return session.execute_read(query_fuzzy_match, keyword)

    def _query_with_vector_sim(self, keyword, kgdb_name="neo4j", threshold=0.9):
        """vectorquery"""
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        def _index_exists(tx, index_name):
            """Check if index exists"""
            result = tx.run("SHOW INDEXES")
            for record in result:
                if record["name"] == index_name:
                    return True
            return False

        def query_by_vector(tx, text, threshold):
            # First check whether index exists
            if not _index_exists(tx, "entityEmbeddings"):
                raise Exception(
                    "Vector index does not exist. Please create the index first, or ensure triples have been uploaded in the current graph."
                )

            embedding = self.get_embedding(text)
            result = tx.run(
                """
            CALL db.index.vector.queryNodes('entityEmbeddings', 10, $embedding)
            YIELD node AS similarEntity, score
            WHERE 'Upload' IN labels(similarEntity)
            RETURN similarEntity.name AS name, score
            """,
                embedding=embedding,
            )
            return [r for r in result if r["score"] > threshold]

        with self.driver.session() as session:
            results = session.execute_read(
                query_by_vector, keyword, threshold=threshold)
            return results

    def _query_specific_entity(self, entity_name, kgdb_name="neo4j", hops=2, limit=100):
        """Query triples related to a specific entity (undirected relationships)."""
        assert self.driver is not None, "Database is not connected"
        if not entity_name:
            logger.warning("Entity name is empty")
            return []

        self.use_database(kgdb_name)

        def _process_record_props(record):
            """Process record properties: flatten properties and remove embedding."""
            if record is None:
                return None

            # Copy to avoid mutating the original dictionary.
            data = dict(record)
            props = data.pop("properties", {}) or {}

            # remove embedding
            if "embedding" in props:
                del props["embedding"]

            # Merge properties (preserve core fields from original dict when possible).
            return {**props, **data}

        def query(tx, entity_name, hops, limit):
            try:
                query_str = """
                WITH [
                    // 1-hop outgoing edges
                    [(n:Upload {name: $entity_name})-[r1]->(m1) |
                     {h: {id: elementId(n), name: n.name, properties: properties(n)},
                      r: {
                        id: elementId(r1),
                        type: r1.type,
                        source_id: elementId(n),
                        target_id: elementId(m1),
                        properties: properties(r1)
                      },
                      t: {id: elementId(m1), name: m1.name, properties: properties(m1)}}],
                                        // 2-hop outgoing edges
                    [(n:Upload {name: $entity_name})-[r1]->(m1)-[r2]->(m2) |
                     {h: {id: elementId(m1), name: m1.name, properties: properties(m1)},
                      r: {
                        id: elementId(r2),
                        type: r2.type,
                        source_id: elementId(m1),
                        target_id: elementId(m2),
                        properties: properties(r2)
                      },
                      t: {id: elementId(m2), name: m2.name, properties: properties(m2)}}],
                                        // 1-hop incoming edges
                    [(m1)-[r1]->(n:Upload {name: $entity_name}) |
                     {h: {id: elementId(m1), name: m1.name, properties: properties(m1)},
                      r: {
                        id: elementId(r1),
                        type: r1.type,
                        source_id: elementId(m1),
                        target_id: elementId(n),
                        properties: properties(r1)
                      },
                      t: {id: elementId(n), name: n.name, properties: properties(n)}}],
                                        // 2-hop incoming edges
                    [(m2)-[r2]->(m1)-[r1]->(n:Upload {name: $entity_name}) |
                     {h: {id: elementId(m2), name: m2.name, properties: properties(m2)},
                      r: {
                        id: elementId(r2),
                        type: r2.type,
                        source_id: elementId(m2),
                        target_id: elementId(m1),
                        properties: properties(r2)
                      },
                      t: {id: elementId(m1), name: m1.name, properties: properties(m1)}}]
                ] AS all_results
                UNWIND all_results AS result_list
                UNWIND result_list AS item
                RETURN item.h AS h, item.r AS r, item.t AS t
                LIMIT $limit
                """
                results = tx.run(
                    query_str, entity_name=entity_name, limit=limit)

                if not results:
                    logger.info(
                        f"No related information found for entity {entity_name}")
                    return {}

                formatted_results = {"nodes": [], "edges": [], "triples": []}

                for item in results:
                    h = _process_record_props(item["h"])
                    r = _process_record_props(item["r"])
                    t = _process_record_props(item["t"])

                    formatted_results["nodes"].extend([h, t])
                    formatted_results["edges"].append(r)
                    formatted_results["triples"].append(
                        (h["name"], r["type"], t["name"]))

                logger.debug(f"Query Results: {results}")
                return formatted_results

            except Exception as e:
                logger.error(f"queryentity {entity_name} failed: {str(e)}")
                return []

        try:
            with self.driver.session() as session:
                return session.execute_read(query, entity_name, hops, limit)

        except Exception as e:
            logger.error(f"databasesessionexception: {str(e)}")
            return []
