import asyncio
import json
import os
import traceback
import warnings

from yunesa import config
from yunesa.knowledge.graphs.adapters.base import Neo4jConnectionManager
from yunesa.models import select_embedding_model
from yunesa.utils import logger
from yunesa.utils.datetime_utils import utc_isoformat

warnings.filterwarnings("ignore", category=UserWarning)


class CoreGraphService:
    """
    Core Graph Service for Neo4j management and querying.
    Handles connection management, graph statistics, and structured data retrieval for visualizations.
    """

    def __init__(self, db_manager: Neo4jConnectionManager = None):
        self.connection = db_manager or Neo4jConnectionManager()
        self.kgdb_name = "neo4j"
        self.embed_model_name = None
        self.embed_model = None
        self.work_dir = os.path.join(
            config.save_dir, "knowledge_graph", self.kgdb_name)
        os.makedirs(self.work_dir, exist_ok=True)
        self.is_initialized_from_file = False

        # Attempt to load saved graph database info
        self.load_graph_info()

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

    def use_database(self, kgdb_name="neo4j"):
        """Switch to specified database"""
        assert kgdb_name == self.kgdb_name, (
            f"Provided database name '{kgdb_name}' does not match current instance database name '{self.kgdb_name}'"
        )
        if self.status == "closed":
            self.start()

    def get_graph_info(self, graph_name="neo4j"):
        """Get statistics and info about the graph database"""
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
            }

        try:
            if self.is_running():
                with self.driver.session() as session:
                    graph_info = session.execute_read(query)
                    graph_info["last_updated"] = utc_isoformat()
                    return graph_info
            else:
                return None
        except Exception as e:
            logger.error(
                f"Failed to get graph database info: {e}, {traceback.format_exc()}")
            return None

    def save_graph_info(self, graph_name="neo4j"):
        """Save basic graph database info to a JSON file"""
        try:
            graph_info = self.get_graph_info(graph_name)
            if graph_info is None:
                return False

            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            with open(info_file_path, "w", encoding="utf-8") as f:
                json.dump(graph_info, f, ensure_ascii=False, indent=2)

            self.is_initialized_from_file = True
            return True
        except Exception as e:
            logger.error(f"Failed to save graph database info: {e}")
            return False

    def load_graph_info(self):
        """Load basic graph database info from JSON file"""
        try:
            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            if not os.path.exists(info_file_path):
                return False

            with open(info_file_path, encoding="utf-8") as f:
                graph_info = json.load(f)

            if graph_info.get("embed_model_name"):
                self.embed_model_name = graph_info["embed_model_name"]
                self.embed_model = select_embedding_model(self.embed_model_name)

            self.is_initialized_from_file = True
            return True
        except Exception as e:
            logger.error(f"Failed to load graph database info: {e}")
            return False

    async def aget_embedding(self, text, batch_size=None):
        if self.embed_model is None:
            self.embed_model = select_embedding_model(config.embed_model)
            
        if isinstance(text, list):
            outputs = await self.embed_model.abatch_encode(text, batch_size=batch_size or 40)
            return outputs
        else:
            outputs = await self.embed_model.aencode(text)
            return outputs

    def get_embedding(self, text, batch_size=None):
        if self.embed_model is None:
            self.embed_model = select_embedding_model(config.embed_model)

        if isinstance(text, list):
            outputs = self.embed_model.batch_encode(text, batch_size=batch_size or 40)
            return outputs
        else:
            outputs = self.embed_model.encode([text])[0]
            return outputs

    @staticmethod
    def _embedding_to_list(embedding):
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        return [float(value) for value in embedding]

    async def add_embedding_to_nodes(self, kgdb_name="neo4j", batch_size=40):
        """Add embedding vectors to Entity nodes that do not have them yet."""
        return await asyncio.to_thread(
            self._add_embedding_to_nodes_sync,
            kgdb_name,
            batch_size,
        )

    def _add_embedding_to_nodes_sync(self, kgdb_name="neo4j", batch_size=40):
        self.use_database(kgdb_name)
        indexed_count = 0
        embedding_dim = None

        def fetch_batch(tx, limit):
            result = tx.run(
                """
                MATCH (n:Entity)
                WHERE n.embedding IS NULL AND n.name IS NOT NULL
                RETURN elementId(n) AS id, n.name AS name
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(record) for record in result]

        def write_batch(tx, rows):
            result = tx.run(
                """
                UNWIND $rows AS row
                MATCH (n:Entity)
                WHERE elementId(n) = row.id
                SET n.embedding = row.embedding
                RETURN count(n) AS count
                """,
                rows=rows,
            )
            return result.single()["count"]

        with self.driver.session() as session:
            while True:
                rows = session.execute_read(fetch_batch, batch_size)
                if not rows:
                    break

                embeddings = self.get_embedding([row["name"] for row in rows], batch_size=batch_size)
                update_rows = []
                for row, embedding in zip(rows, embeddings, strict=False):
                    embedding_values = self._embedding_to_list(embedding)
                    if embedding_dim is None:
                        embedding_dim = len(embedding_values)
                    update_rows.append({"id": row["id"], "embedding": embedding_values})

                indexed_count += session.execute_write(write_batch, update_rows)

            if embedding_dim is None:
                embedding_dim = session.execute_read(self._get_existing_embedding_dimension)

            if embedding_dim:
                session.execute_write(self._ensure_entity_vector_index, embedding_dim)

        self.embed_model_name = config.embed_model
        self.save_graph_info(kgdb_name)
        return indexed_count

    @staticmethod
    def _get_existing_embedding_dimension(tx):
        result = tx.run(
            """
            MATCH (n:Entity)
            WHERE n.embedding IS NOT NULL
            RETURN size(n.embedding) AS dimension
            LIMIT 1
            """
        ).single()
        return result["dimension"] if result else None

    @staticmethod
    def _ensure_entity_vector_index(tx, dimension):
        tx.run(
            f"""
            CREATE VECTOR INDEX entityEmbeddings IF NOT EXISTS
            FOR (n:Entity) ON (n.embedding)
            OPTIONS {{indexConfig: {{
              `vector.dimensions`: {int(dimension)},
              `vector.similarity_function`: 'cosine'
            }}}}
            """
        )

    def query_node(
        self, keyword, threshold=0.9, kgdb_name="neo4j", hops=2, max_entities=8, return_format="graph", **kwargs
    ):
        """Query nodes for visual citation graph visualization"""
        assert self.driver is not None, "Database is not connected"
        self.use_database(kgdb_name)

        tokens = [t for t in str(keyword).split(" ") if t]
        if not tokens:
            tokens = [str(keyword)]

        entity_to_score = {}
        for token in tokens:
            # Query using vector index
            try:
                results_sim = self._query_with_vector_sim(token, kgdb_name, threshold)
                for r in results_sim:
                    name = r["name"]
                    score = float(r["score"])
                    entity_to_score[name] = max(entity_to_score.get(name, 0.0), score)
            except Exception as e:
                logger.debug(f"Vector query failed for {token}: {e}")

            # Fuzzy query fallback
            results_fuzzy = self._query_with_fuzzy_match(token, kgdb_name)
            for fr in results_fuzzy:
                name = fr[0]
                entity_to_score[name] = max(entity_to_score.get(name, 0.0), 0.3)

        sorted_entity_to_score = sorted(
            entity_to_score.items(), key=lambda x: x[1], reverse=True)
        qualified_entities = [name for name, _ in sorted_entity_to_score][:max_entities]

        all_query_results = {"nodes": [], "edges": [], "triples": []}
        for entity in qualified_entities:
            query_result = self._query_specific_entity(
                entity_name=entity, kgdb_name=kgdb_name, hops=hops)
            if return_format == "graph":
                all_query_results["nodes"].extend(query_result.get("nodes", []))
                all_query_results["edges"].extend(query_result.get("edges", []))
            elif return_format == "triples":
                all_query_results["triples"].extend(query_result.get("triples", []))

        # Deduplication
        if return_format == "graph":
            seen_nodes = {}
            for n in all_query_results["nodes"]:
                seen_nodes[n["id"]] = n
            all_query_results["nodes"] = list(seen_nodes.values())

            seen_edges = {}
            for e in all_query_results["edges"]:
                key = (e["source_id"], e["target_id"], e["type"])
                seen_edges[key] = e
            all_query_results["edges"] = list(seen_edges.values())

        return all_query_results

    def _query_with_fuzzy_match(self, keyword, kgdb_name="neo4j"):
        self.use_database(kgdb_name)
        def query_fuzzy(tx, kw):
            result = tx.run(
                "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($kw) RETURN DISTINCT n.name AS name",
                kw=kw
            )
            return result.values()
        with self.driver.session() as session:
            return session.execute_read(query_fuzzy, keyword)

    def _query_with_vector_sim(self, keyword, kgdb_name="neo4j", threshold=0.9):
        self.use_database(kgdb_name)
        def query_vector(tx, kw, th):
            embedding = self.get_embedding(kw)
            result = tx.run(
                """
                CALL db.index.vector.queryNodes('entityEmbeddings', 10, $embedding)
                YIELD node AS similarEntity, score
                RETURN similarEntity.name AS name, score
                """,
                embedding=embedding,
            )
            return [r for r in result if r["score"] > th]
        with self.driver.session() as session:
            return session.execute_read(query_vector, keyword, threshold)

    def _query_specific_entity(self, entity_name, kgdb_name="neo4j", hops=2, limit=100):
        self.use_database(kgdb_name)

        def _process_record(record):
            if not record: return None
            data = dict(record)
            props = data.pop("properties", {}) or {}
            if "embedding" in props: del props["embedding"]
            return {**props, **data}

        def query(tx, name, limit):
            query_str = """
            MATCH (n:Entity {name: $name})
            OPTIONAL MATCH (n)-[r]-(m:Entity)
            RETURN 
                {id: elementId(n), name: n.name, properties: properties(n)} as h,
                {id: elementId(r), type: type(r), source_id: elementId(startNode(r)), target_id: elementId(endNode(r)), properties: properties(r)} as r,
                {id: elementId(m), name: m.name, properties: properties(m)} as t
            LIMIT $limit
            """
            results = tx.run(query_str, name=name, limit=limit)
            res = {"nodes": [], "edges": [], "triples": []}
            for item in results:
                h = _process_record(item["h"])
                r = _process_record(item["r"])
                t = _process_record(item["t"])
                if h: res["nodes"].append(h)
                if t: res["nodes"].append(t)
                if r: 
                    res["edges"].append(r)
                    res["triples"].append((h["name"], r["type"], t["name"]))
            return res

        with self.driver.session() as session:
            return session.execute_read(query, entity_name, limit)

