!pip install gliner_spacy

!pip install icecream
!pip install pyinstrument
!pip install glirel
!pip install matplotlib
!pip install networkx
!pip install pandas
!pip install pyvis

!pip install loguru # Added to resolve ModuleNotFoundError

from collections import defaultdict
from dataclasses import dataclass
import itertools
import os
import typing
import warnings

from gliner_spacy.pipeline import GlinerSpacy
from icecream import ic
from pydantic import BaseModel
from pyinstrument import Profiler
import glirel
import matplotlib
import matplotlib.colors
import networkx as nx
import pandas as pd
import pyvis
import spacy
import transformers

!python3 -m spacy download en_core_web_md

transformers.logging.set_verbosity_error()
os.environ["TOKENIZERS_PARALLELISM"] = "0"

!pip install watermark
%load_ext watermark
%watermark
%watermark --iversions

profiler: Profiler = Profiler()
profiler.start()

CHUNK_SIZE: int = 1024

GLINER_MODEL: str = "urchade/gliner_small-v2.1"

NER_LABELS: typing.List[ str] = [
    "Behavior",
    "City",
    "Company",
    "Condition",
    "Conference",
    "Country",
    "Food",
    "Food Additive",
    "Hospital",
    "Organ",
    "Organization",
    "People Group",
    "Person",
    "Publication",
    "Research",
    "Science",
    "University",
]

RE_LABELS: dict = {
    "glirel_labels": {
        "no_relation": {},
        "co_founder": {"allowed_head": ["PERSON"], "allowed_tail": ["ORG"]},
        "country_of_origin": {"allowed_head": ["PERSON", "ORG"], "allowed_tail": ["LOC", "GPE"]},
        "parent": {"allowed_head": ["PERSON"], "allowed_tail": ["PERSON"]},
        "followed_by": {"allowed_head": ["PERSON", "ORG"], "allowed_tail": ["PERSON", "ORG"]},
        "spouse": {"allowed_head": ["PERSON"], "allowed_tail": ["PERSON"]},
        "child": {"allowed_head": ["PERSON"], "allowed_tail": ["PERSON"]},
        "founder": {"allowed_head": ["PERSON"], "allowed_tail": ["ORG"]},
        "headquartered_in": {"allowed_head": ["ORG"], "allowed_tail": ["LOC", "GPE", "FAC"]},
        "acquired_by": {"allowed_head": ["ORG"], "allowed_tail": ["ORG", "PERSON"]},
        "subsidiary_of": {"allowed_head": ["ORG"], "allowed_tail": ["ORG", "PERSON"]},
    }
}

SPACY_MODEL: str = "en_core_web_md"

STOP_WORDS: typing.Set[ str ] = set([
    "PRON.it",
    "PRON.that",
    "PRON.they",
    "PRON.those",
    "PRON.we",
    "PRON.which",
    "PRON.who",
])

TR_ALPHA: float = 0.85
TR_LOOKBACK: int = 3

nlp: spacy.Language = spacy.load(SPACY_MODEL)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    nlp.add_pipe(
        "gliner_spacy",
        config = {
            "gliner_model": GLINER_MODEL,
            "labels": NER_LABELS,
            "chunk_size": CHUNK_SIZE,
            "style": "ent",
        },
    )

    nlp.add_pipe(
        "glirel",
        after = "ner",
    );

graph: nx.Graph = nx.Graph()
known_lemma: typing.List[ str ] = []

class TextChunk (BaseModel):
    uid: int
    url: str
    text: str

SAMPLE_CHUNK: TextChunk = TextChunk(
    uid = 1,
    url = "https://www.theguardian.com/society/article/2024/jul/31/eating-processed-red-meat-could-increase-risk-of-dementia-study-finds",
    text = """
Electroencephalography (EEG) is a method for recording the electrical activity of the brain. In the EEG various frequency signals can analyse the brain and the brain's behaviour. EEG can detect the abnormalities in the brain, one of the abnormality is Autism Spectrum Disorder (ASD). ASD is a condition where a person has a combination of neurological disorders in social communication and behavior, limited interest in something and sensory behavior. Joint attention (JA) is the ability in sharing attention between interactive social partner with third external elements as objects or events. Joint attention can also be said as social interaction behaviors to follow the attention of others, and direct attention of another. Joint attention is the key point affecting social communication in individuals with autism spectrum disorder (ASD). In this study, the detection of the ability of ASD sufferers to respond to instructions to see a targeted object based on the EEG signal recording was conducted. The dataset used is BCIAUT P-300 that is non-linear separable and imbalanced class with a ratio of 1: 8. In handling the imbalanced data, undersampling was applied. The feature extraction method that compared are wavelet and principal component analysis. Based on the experiment result, Pz has the best channel to classify the Joint Attention of ASD using EEG P-300 data. The best accuracy is GRLVQ and the best G-mean is SVM. Over all the results, based on accuracy, g-mean, training and testing time show that GRLVQ is better performance than others, and SVM is the runner up. The differences of accuracy 9%, training time GRLVQ faster around 45 seconds than SVM, and testing time faster around 3 seconds.  """.strip(),
)

chunk: TextChunk = SAMPLE_CHUNK

doc: spacy.tokens.doc.Doc = list(
    nlp.pipe(
        [( chunk.text, RE_LABELS )],
        as_tuples = True,
    )
)[0][0]

def to_nltk_tree (node):
    if node.n_lefts + node.n_rights > 0:
        return Tree(node.orth_, [to_nltk_tree(child) for child in node.children])
    else:
        return node.orth_

[to_nltk_tree(sent.root).pretty_print() for sent in doc.sents]

for sent in doc.sents:
    node_seq: typing.List[ int ] = []
    ic(sent)

    for tok in sent:
        text: str = tok.text.strip()

        if tok.pos_ in [ "NOUN", "PROPN" ]:
            key: str = tok.pos_ + "." + tok.lemma_.strip().lower()
            print(tok.i, key, tok.text.strip())

            if key not in known_lemma:
                # create a new node
                known_lemma.append(key)
                node_id: int = known_lemma.index(key)
                node_seq.append(node_id)

                graph.add_node(
                    node_id,
                    key = key,
                    kind = "Lemma",
                    pos = tok.pos_,
                    text = text,
                    chunk = chunk.uid,
                    count = 1,
                )
            else:
                # link to an existing node, adding weight
                node_id = known_lemma.index(key)
                node_seq.append(node_id)

                node: dict = graph.nodes[node_id]
                node["count"] += 1

    # create the textrank edges
    ic(node_seq)

    for hop in range(TR_LOOKBACK):
        for node_id, node in enumerate(node_seq[: -1 - hop]):
            neighbor: int = node_seq[hop + node_id + 1]
            graph.add_edge(
                node,
                neighbor,
                rel = "FOLLOWS_LEXICALLY",
            )

sent_map: typing.Dict[ spacy.tokens.span.Span, int ] = {}

for sent_id, sent in enumerate(doc.sents):
    sent_map[sent] = sent_id

@dataclass(order=False, frozen=False)
class Entity:
    loc: typing.Tuple[ int ]
    key: str
    text: str
    label: str
    chunk_id: int
    sent_id: int
    span: spacy.tokens.span.Span
    node: typing.Optional[ int ] = None


span_decoder: typing.Dict[ tuple, Entity ] = {}


def make_entity (
    span: spacy.tokens.span.Span,
    chunk: TextChunk,
    ) -> Entity:
    """
Instantiate one `Entity` dataclass object, adding it to the working "vocabulary".
    """
    key: str = " ".join([
        tok.pos_ + "." + tok.lemma_.strip().lower()
        for tok in span
    ])

    ent: Entity = Entity(
        ( span.start, span.end, ),
        key,
        span.text,
        span.label_,
        chunk.uid,
        sent_map[span.sent],
        span,
    )

    if ent.loc not in span_decoder:
        span_decoder[ent.loc] = ent
        ic(ent)

    return ent

for span in doc.ents:
    make_entity(span, chunk)

for span in doc.noun_chunks:
    make_entity(span, chunk)

def extract_entity (
    ent: Entity,
    ) -> None:
    """
Link one `Entity` into the existing graph.
    """
    if ent.key not in known_lemma:
        # add a new Entity node to the graph and link to its component Lemma nodes
        known_lemma.append(ent.key)
        node_id: int = known_lemma.index(ent.key)

        graph.add_node(
            node_id,
            key = ent.key,
            kind = "Entity",
            label = ent.label,
            pos = "NP",
            text = ent.text,
            chunk = ent.chunk_id,
            count = 1,
        )

        for tok in ent.span:
            tok_key: str = tok.pos_ + "." + tok.lemma_.strip().lower()

            if tok_key in known_lemma:
                tok_idx: int = known_lemma.index(tok_key)

                graph.add_edge(
                    node_id,
                    tok_idx,
                    rel = "COMPOUND_ELEMENT_OF",
                )
    else:
        node_id: int = known_lemma.index(ent.key)
        node: dict = graph.nodes[node_id]
        # promote to an Entity, in case the node had been a Lemma
        node["kind"] = "Entity"
        node["chunk"] = ent.chunk_id
        node["count"] += 1

        # select the more specific label
        if "label" not in node or node["label"] == "NP":
          node["label"] = ent.label

    ent.node = node_id

for ent in span_decoder.values():
    if ent.key not in STOP_WORDS:
        extract_entity(ent)
        ic(ent)

relations: typing.List[ dict ] = sorted(
    doc._.relations,
    key = lambda x: x["score"],
    reverse = True,
)

for item in relations:
    src_loc: typing.Tuple[ int ] = tuple(item["head_pos"])
    dst_loc: typing.Tuple[ int ] = tuple(item["tail_pos"])
    skip_rel: bool = False

    if src_loc not in span_decoder:
        print("MISSING src entity:", item["head_text"], item["head_pos"])

        src_ent: Entity = make_entity(
            doc[ item["head_pos"][0] : item["head_pos"][1] ],
            chunk,
        )

        if src_ent.key in STOP_WORDS:
            skip_rel = True
        else:
            extract_entity(src_ent)

    if dst_loc not in span_decoder:
        print("MISSING dst entity:", item["tail_text"], item["tail_pos"])

        dst_ent: Entity = make_entity(
            doc[ item["tail_pos"][0] : item["tail_pos"][1] ],
            chunk,
        )

        if dst_ent.key in STOP_WORDS:
            skip_rel = True
        else:
            extract_entity(dst_ent)

    # link the connected nodes
    if not skip_rel:
        src_ent = span_decoder[src_loc]
        dst_ent = span_decoder[dst_loc]

        rel: str = item["label"].strip().replace(" ", "_").upper()
        prob: float = round(item["score"], 3)

        print(f"{src_ent.text} {src_ent.node} -> {rel} -> {dst_ent.text} {dst_ent.node} | {prob}")

        graph.add_edge(
            src_ent.node,
            dst_ent.node,
            rel = rel,
            prob = prob,
        )

ent_map: typing.Dict[ int, typing.Set[ int ]] = defaultdict(set)

for ent in span_decoder.values():
    if ent.node is not None:
        ent_map[ent.sent_id].add(ent.node)

for sent_id, nodes in ent_map.items():
    for pair in itertools.combinations(list(nodes), 2):
        if not graph.has_edge(*pair):
            graph.add_edge(
                pair[0],
                pair[1],
                rel = "CO_OCCURS_WITH",
                prob = 1.0,
            )

for node, rank in nx.pagerank(graph, alpha = TR_ALPHA, weight = "count").items():
    graph.nodes[node]["rank"] = rank

df: pd.DataFrame = pd.DataFrame([
    node_attr
    for node, node_attr in graph.nodes(data = True)
    if node_attr["kind"] == "Entity"
]).sort_values(by = [ "rank", "count" ], ascending = False)

df.head(20)

pv_net: pyvis.network.Network = pyvis.network.Network(
    height = "750px",
    width = "100%",
    notebook = True,
    cdn_resources = "remote",
)

for node_id, node_attr in graph.nodes(data = True):
    if node_attr["kind"] == "Entity":
        color: str = "hsl(65, 46%, 58%)"
        size: int = round(200 * node_attr["rank"])
    else:
        color = "hsla(72, 10%, 90%, 0.95)"
        size = round(30 * node_attr["rank"])

    pv_net.add_node(
        node_id,
        label = node_attr["text"],
        title = node_attr.get("label"),
        color = color,
        size = size,
    )

for src_node, dst_node, edge_attr in graph.edges(data = True):
    pv_net.add_edge(
        src_node,
        dst_node,
        title = edge_attr.get("rel"),
    )

pv_net.toggle_physics(True)
pv_net.show("chunk.html")

communities: typing.Generator = nx.community.louvain_communities(graph)

comm_map: typing.Dict[ int, int ] = {
    node_id: i
    for i, comm in enumerate(communities)
    for node_id in comm
}

xkcd_colors: typing.List[ str ] = list(matplotlib.colors.XKCD_COLORS.values())

colors: typing.List[ str ] = [
    xkcd_colors[comm_map[n]]
    for n in list(graph.nodes())
]

labels: typing.Dict[ int, str ] = {
    node_id: node_attr["text"]
    for node_id, node_attr in graph.nodes(data = True)
}

SPRING_DISTANCE: float = 2.5

nx.draw_networkx(
    graph,
    pos = nx.spring_layout(
        graph,
        k = SPRING_DISTANCE / len(communities),
    ),
    labels = labels,
    node_color = colors,
    edge_color = "#bbb",
    with_labels = True,
    font_size = 8,
)

ic(len(known_lemma))
ic(len(span_decoder))
ic(len(graph.nodes()));

profiler.stop()
profiler.print()

for x in known_lemma:
    if "PRON" in x:
        print(x)

kept_nodes: typing.Set[ int ] = set()

for node_id, node_attr in graph.nodes(data = True):
    if node_attr["kind"] == "Entity":
        print(node_id, node_attr["key"], node_attr["rank"], node_attr["label"], node_attr["text"], node_attr["chunk"])
        kept_nodes.add(node_id)

skip_rel: typing.Set[ str ] = set([ "FOLLOWS_LEXICALLY", "COMPOUND_ELEMENT_OF" ])

for src_id, dst_id, edge_attr in graph.edges(data = True):
    if src_id in kept_nodes and dst_id in kept_nodes:
        rel: str = edge_attr["rel"]

        if rel not in skip_rel:
            print(src_id, dst_id, rel, edge_attr["prob"])



