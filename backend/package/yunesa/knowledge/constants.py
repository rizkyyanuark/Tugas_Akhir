"""
constants.py — UNESA Academic Knowledge Graph Constants
=========================================================
Ontology, labels, collections, patterns, and default concept aliases.
"""

STRUCTURAL_NODE_TYPES = {
    "Lecturer",
    "Publication",
    "Venue",
    "Concept",
}

CONCEPT_TYPES = {
    "Problem",
    "ResearchTopic",
    "Task",
    "Method",
    "Model",
    "Dataset",
    "Metric",
    "Result",
    "Results",
    "Innovation",
    "Domain",
    "Field",
    "Keyword",
}

VALID_CONCEPT_TYPES = CONCEPT_TYPES

CONCEPT_EDGE_BY_TYPE = {
    "Problem": "SOLVES_PROBLEM",
    "ResearchTopic": "HAS_TOPIC",
    "Task": "WORKS_ON_TASK",
    "Method": "USES_METHOD",
    "Model": "USES_MODEL",
    "Dataset": "USES_DATASET",
    "Metric": "EVALUATED_WITH",
    "Result": "HAS_RESULT",
    "Results": "HAS_RESULT",
    "Innovation": "PROPOSES_INNOVATION",
    "Domain": "BELONGS_TO_DOMAIN",
    "Field": "BELONGS_TO_DOMAIN",
    "Keyword": "HAS_KEYWORD",
}

CONCEPT_TYPE_PRIORITY = {
    "Model": 10,
    "Method": 9,
    "Dataset": 8,
    "Metric": 7,
    "Problem": 6,
    "Task": 5,
    "Domain": 4,
    "Field": 4,
    "ResearchTopic": 3,
    "Result": 2,
    "Results": 2,
    "Innovation": 2,
    "Keyword": 1,
}

AUTHOR_RELATIONS = {"HAS_AUTHOR", "PUBLISHES", "WRITES"}
CONCEPT_RELATIONS = set(CONCEPT_EDGE_BY_TYPE.values())
ONTOLOGY_RELATIONS = {
    "PUBLISHES",
    "HAS_AUTHOR",
    "HAS_TOPIC",
    "SOLVES_PROBLEM",
    "WORKS_ON_TASK",
    "PROPOSES_INNOVATION",
    "USES_METHOD",
    "USES_MODEL",
    "USES_DATASET",
    "EVALUATED_WITH",
    "HAS_RESULT",
    "HAS_AFFILIATION",
    "BELONGS_TO_DOMAIN",
    "COLLABORATES_WITH",
    "PUBLISHED_IN_VENUE",
    "HAS_KEYWORD",
    "SKOS_RELATED",
    "SKOS_EXACT_MATCH",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "RELATED_TO",
}

RELATION_ALIASES = {
    "WRITES": "PUBLISHES",
    "WORKS_ON": "WORKS_ON_TASK",
    "SOLVES": "SOLVES_PROBLEM",
    "EVALUATED_BY": "EVALUATED_WITH",
    "IN_FIELD": "BELONGS_TO_DOMAIN",
    "AFFILIATED_WITH": "HAS_AFFILIATION",
    "USES": "USES_METHOD",
    "PROPOSED": "PROPOSES_INNOVATION",
}

GLINER_LABEL_TO_CONCEPT_TYPE = {
    "research problem": "Problem",
    "problem": "Problem",
    "research topic": "ResearchTopic",
    "topic": "ResearchTopic",
    "research task": "Task",
    "task": "Task",
    "application domain": "Domain",
    "domain": "Domain",
    "field": "Domain",
    "method": "Method",
    "algorithm": "Method",
    "model": "Model",
    "dataset": "Dataset",
    "data source": "Dataset",
    "metric": "Metric",
    "evaluation metric": "Metric",
    "result": "Result",
    "main result": "Result",
    "innovation": "Innovation",
    "keyword": "Keyword",
}

ACADEMIC_NER_LABELS = [
    "research problem",
    "research topic",
    "research task",
    "application domain",
    "method",
    "algorithm",
    "model",
    "dataset",
    "data source",
    "evaluation metric",
    "main result",
    "innovation",
]

ACADEMIC_RELATION_LABELS = [
    "works on",
    "solves",
    "uses method",
    "uses model",
    "uses dataset",
    "evaluated by",
    "has result",
    "belongs to domain",
    "innovates",
]

GLIREL_RELATION_TO_EDGE = {
    "works on": "WORKS_ON_TASK",
    "solves": "SOLVES_PROBLEM",
    "uses method": "USES_METHOD",
    "uses model": "USES_MODEL",
    "uses dataset": "USES_DATASET",
    "evaluated by": "EVALUATED_WITH",
    "has result": "HAS_RESULT",
    "belongs to domain": "BELONGS_TO_DOMAIN",
    "innovates": "PROPOSES_INNOVATION",
}

DEFAULT_MILVUS_COLLECTIONS = {
    "chunks": "chunks_vdb",
    "entities": "entities_vdb",
    "relationships": "relationships_vdb",
}

DEFAULT_EMBEDDING_PROVIDER = "siliconflow"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_DIM = 1024
SILICONFLOW_EMBEDDING_DIMS = {
    "Qwen/Qwen3-Embedding-0.6B": 1024,
    "Qwen/Qwen3-Embedding-4B": 2560,
    "Qwen/Qwen3-Embedding-8B": 4096,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}

DEFAULT_GLINER_MODEL = "gliner-community/gliner_xxl-v2.5"
DEFAULT_GLIREL_MODEL = "jackboyla/glirel-large-v0"

MILVUS_VARCHAR_LIMITS = {
    "chunks_vdb": {
        "graphName": 256,
        "title": 1024,
        "content": 8192,
        "year": 16,
        "paperUrl": 1024,
        "authors": 2048,
    },
    "entities_vdb": {
        "graphName": 256,
        "entityName": 512,
        "entityType": 256,
        "description": 4096,
        "nodeId": 256,
        "sourceId": 256,
    },
    "relationships_vdb": {
        "graphName": 256,
        "srcId": 256,
        "tgtId": 256,
        "relType": 256,
        "description": 4096,
        "sourceId": 256,
    },
    # Backward compatibility aliases
    "PaperChunk": {
        "graphName": 256,
        "title": 1024,
        "content": 8192,
        "year": 16,
        "paperUrl": 1024,
        "authors": 2048,
    },
    "EntityEmbedding": {
        "graphName": 256,
        "entityName": 512,
        "entityType": 256,
        "description": 4096,
        "nodeId": 256,
        "sourceId": 256,
    },
    "RelationshipEmbedding": {
        "graphName": 256,
        "srcId": 256,
        "tgtId": 256,
        "relType": 256,
        "description": 4096,
        "sourceId": 256,
    },
}

MODEL_PATTERNS = [
    r"\bbert\b",
    r"\bindobert\b",
    r"\btransformer\b",
    r"\bvision transformer\b",
    r"\bvit\b",
    r"\bmobilevit\b",
    r"\befficientnet\b",
    r"\bxgboost\b",
    r"\bcnn\b",
    r"\brnn\b",
    r"\blstm\b",
    r"\bgru\b",
    r"\bbi[- ]?lstm\b",
    r"\bbi[- ]?gru\b",
    r"\byolo\b",
    r"\bresnet\b",
    r"\bsupport vector machine[s]?\b",
    r"\bsvm\b",
    r"\brandom forest\b",
    r"\bnaive bayes\b",
    r"\blightgbm\b",
    r"\bcatboost\b",
]

METHOD_PATTERNS = [
    r"\balgorithm\b",
    r"\bmethod\b",
    r"\bapproach\b",
    r"\btechnique\b",
    r"\bframework\b",
    r"\boptimization\b",
    r"\boptimizer\b",
    r"\boptuna\b",
    r"\bboosting\b",
    r"\bensemble learning\b",
    r"\bmetaheuristic\b",
    r"\bclassification\b",
    r"\bclustering\b",
    r"\bregression\b",
    r"\bdeep learning\b",
    r"\bmachine learning\b",
    r"\bnatural language processing\b",
    r"\bcomputer vision\b",
]

TASK_PATTERNS = [
    r"\bclassification\b",
    r"\bdetection\b",
    r"\bprediction\b",
    r"\bsegmentation\b",
    r"\brecommendation\b",
    r"\branking\b",
    r"\bforecasting\b",
    r"\brecognition\b",
    r"\bentity extraction\b",
    r"\binformation retrieval\b",
    r"\bsentiment analysis\b",
]

DATASET_PATTERNS = [
    r"\bdataset\b",
    r"\bdata set\b",
    r"\bcorpus\b",
    r"\bbenchmark\b",
    r"\baptos\b",
    r"\bimagenet\b",
    r"\bcifar\b",
    r"\bmnist\b",
    r"\bscopus\b",
    r"\bgoogle scholar\b",
    r"\bopenalex\b",
    r"\bsemantic scholar\b",
]

METRIC_PATTERNS = [
    r"\baccuracy\b",
    r"\bprecision\b",
    r"\brecall\b",
    r"\bf1\b",
    r"\bf1-score\b",
    r"\bauc\b",
    r"\brmse\b",
    r"\bmae\b",
    r"\bmape\b",
    r"\bflops\b",
    r"\btime\b",
    r"\bseconds?\b",
    r"\bminutes?\b",
    r"\b\d+(?:\.\d+)?\s*%",
]

DOMAIN_PATTERNS = [
    r"\beducation\b",
    r"\be-learning\b",
    r"\bmedical\b",
    r"\bhealth\b",
    r"\bretina\b",
    r"\bdiabetic retinopathy\b",
    r"\bimage analysis\b",
    r"\bfacial image\b",
    r"\bfinance\b",
    r"\bcredit\b",
    r"\bsolar energy\b",
    r"\brenewable energy\b",
    r"\bsoftware engineering\b",
    r"\binformation system\b",
    r"\bpower system\b",
    r"\bnetwork\b",
    r"\bcybersecurity\b",
]

PROBLEM_PATTERNS = [
    r"\bproblem\b",
    r"\bchallenge\b",
    r"\bissue\b",
    r"\bthreat\b",
    r"\bdisease\b",
    r"\bdiabetic retinopathy\b",
    r"\bcancer\b",
    r"\boscillation\b",
    r"\bclassification problem\b",
]

RESULT_PATTERNS = [
    r"\bresult\b",
    r"\bperformance\b",
    r"\bachiev(?:e|ed|es|ing)\b",
    r"\bimprov(?:e|ed|es|ing|ement)\b",
    r"\breduc(?:e|ed|es|ing|tion)\b",
    r"\boutperform(?:s|ed|ing)?\b",
    r"\boptimal\b",
]

INNOVATION_PATTERNS = [
    r"\bnovel\b",
    r"\bnew\b",
    r"\bpropos(?:e|ed|es|ing)\b",
    r"\bdevelop(?:s|ed|ing)?\b",
    r"\bintroduc(?:e|ed|es|ing)\b",
    r"\bframework\b",
    r"\bhybrid\b",
]

GENERIC_IEEE_TEXT_TERMS = {
    "analysis",
    "analyses",
    "learning",
    "model",
    "models",
    "system",
    "systems",
    "method",
    "methods",
    "performance",
    "data",
    "information",
    "energy",
}

DEFAULT_CONCEPT_ALIASES = {
    "support_vector_machine": {
        "canonical_label": "Support Vector Machine",
        "concept_type": "Model",
        "aliases": ["svm", "support vector machine", "support-vector machine"],
    },
    "convolutional_neural_network": {
        "canonical_label": "Convolutional Neural Network",
        "concept_type": "Model",
        "aliases": ["cnn", "convolutional neural network"],
    },
    "artificial_neural_network": {
        "canonical_label": "Artificial Neural Network",
        "concept_type": "Model",
        "aliases": ["ann", "artificial neural network"],
    },
    "long_short_term_memory": {
        "canonical_label": "Long Short-Term Memory",
        "concept_type": "Model",
        "aliases": ["lstm", "long short term memory", "long short-term memory"],
    },
    "bidirectional_lstm": {
        "canonical_label": "Bidirectional LSTM",
        "concept_type": "Model",
        "aliases": ["bilstm", "bi lstm", "bidirectional lstm"],
    },
    "k_nearest_neighbors": {
        "canonical_label": "K-Nearest Neighbors",
        "concept_type": "Model",
        "aliases": ["knn", "k nearest neighbors", "k-nearest neighbors"],
    },
    "naive_bayes": {
        "canonical_label": "Naive Bayes",
        "concept_type": "Model",
        "aliases": ["naive bayes", "naive bayes classifier"],
    },
    "decision_tree": {
        "canonical_label": "Decision Tree",
        "concept_type": "Model",
        "aliases": ["decision tree", "decision trees", "tree algorithm", "tree algorithms"],
    },
    "efficientnet": {
        "canonical_label": "EfficientNet",
        "concept_type": "Model",
        "aliases": ["efficientnet", "efficient net"],
    },
    "vision_transformer": {
        "canonical_label": "Vision Transformer",
        "concept_type": "Model",
        "aliases": ["vit", "vision transformer"],
    },
    "auc": {
        "canonical_label": "AUC",
        "concept_type": "Metric",
        "aliases": ["auc", "roc auc", "roc-auc", "area under curve", "area under the curve"],
    },
    "accuracy": {
        "canonical_label": "Accuracy",
        "concept_type": "Metric",
        "aliases": ["accuracy", "akurasi"],
    },
    "precision": {
        "canonical_label": "Precision",
        "concept_type": "Metric",
        "aliases": ["precision"],
    },
    "recall": {
        "canonical_label": "Recall",
        "concept_type": "Metric",
        "aliases": ["recall"],
    },
    "f1_score": {
        "canonical_label": "F1-score",
        "concept_type": "Metric",
        "aliases": ["f1", "f1 score", "f1-score", "f1score"],
    },
    "aptos_2019": {
        "canonical_label": "APTOS 2019",
        "concept_type": "Dataset",
        "aliases": ["aptos", "aptos 2019", "aptos dataset", "aptos 2019 blindness detection"],
    },
    "imagenet": {
        "canonical_label": "ImageNet",
        "concept_type": "Dataset",
        "aliases": ["imagenet", "image net"],
    },
    "cifar_10": {
        "canonical_label": "CIFAR-10",
        "concept_type": "Dataset",
        "aliases": ["cifar10", "cifar-10", "cifar 10"],
    },
    "mnist": {
        "canonical_label": "MNIST",
        "concept_type": "Dataset",
        "aliases": ["mnist"],
    },
}
