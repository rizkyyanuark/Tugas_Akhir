import os
import sys
import matplotlib.pyplot as plt
import networkx as nx
from pathlib import Path

# Setup paths
HERE = Path(__file__).resolve().parent
DOCS_GAMBAR_DIR = HERE.parent.parent.parent / "docs" / "proposal tugas akhir" / "Gambar"
DOCS_GAMBAR_DIR.mkdir(parents=True, exist_ok=True)

def generate_subgraph_vis():
    # 1. Subgraph (Local Search)
    G = nx.DiGraph()
    
    pub = "Eksplorasi Teknik Pre-Processing..."
    venue = "JINACS"
    model = "XGBoost"
    lecturer1 = "Achmad Kautsar"
    lecturer2 = "Yuni Yamasari"
    
    G.add_node(pub, type="Publication")
    G.add_node(venue, type="Venue")
    G.add_node(model, type="Concept")
    G.add_node(lecturer1, type="Lecturer")
    G.add_node(lecturer2, type="Lecturer")
    
    # Add edges
    G.add_edge(pub, venue, label="PUBLISHED_IN")
    G.add_edge(pub, model, label="USES_MODEL")
    G.add_edge(pub, lecturer1, label="HAS_AUTHOR")
    G.add_edge(pub, lecturer2, label="HAS_AUTHOR")
    G.add_edge(lecturer1, lecturer2, label="COLLABORATES")

    plt.figure(figsize=(6, 5))
    
    # Closer positions to make the graph compact
    pos = {
        pub: (0, 0.5),
        venue: (-0.9, 1.2),
        model: (0.9, 1.2),
        lecturer1: (-0.6, -0.1),
        lecturer2: (0.6, -0.1)
    }
    
    # Draw nodes by type
    colors = {
        "Publication": "#3498db",  # Blue
        "Venue": "#9b59b6",        # Purple
        "Concept": "#e74c3c",      # Red
        "Lecturer": "#2ecc71"      # Green
    }
    
    for ntype, color in colors.items():
        nlist = [n for n, attr in G.nodes(data=True) if attr.get("type") == ntype]
        if nlist:
            nx.draw_networkx_nodes(G, pos, nodelist=nlist, node_color=color, node_size=7500, alpha=0.9)
        
    nx.draw_networkx_edges(G, pos, edgelist=G.edges(), width=3.0, arrowstyle="->", arrowsize=22, edge_color="#7f8c8d")
    
    # Custom wrapped node labels with much larger font
    labels = {
        pub: "Eksplorasi\nTeknik...",
        venue: "JINACS",
        model: "XGBoost",
        lecturer1: "Achmad\nKautsar",
        lecturer2: "Yuni\nYamasari"
    }
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=15, font_weight="bold")
    
    # Draw edge labels with much larger font
    edge_labels = nx.get_edge_attributes(G, "label")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=12)
    
    plt.axis("off")
    
    # Set limits manually with extra padding to prevent cropping of large node circles
    x_coords = [coords[0] for coords in pos.values()]
    y_coords = [coords[1] for coords in pos.values()]
    plt.xlim(min(x_coords) - 0.55, max(x_coords) + 0.55)
    plt.ylim(min(y_coords) - 0.55, max(y_coords) + 0.55)
    
    plt.tight_layout(pad=0.1)
    
    out_path = DOCS_GAMBAR_DIR / "sample_subgraph.png"
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print("[OK] Saved:", out_path)

def generate_hybrid_vis():
    # 2. Hybrid (Global Search)
    G = nx.DiGraph()
    
    pub1 = "Implementing Optuna..."
    pub2 = "Eksplorasi Teknik..."
    lecturer1 = "R. C. Wibawa"
    lecturer2 = "Achmad Kautsar"
    lecturer3 = "Yuni Yamasari"
    model1 = "CatBoost"
    model2 = "XGBoost"
    
    G.add_node(pub1, type="Publication")
    G.add_node(pub2, type="Publication")
    G.add_node(lecturer1, type="Lecturer")
    G.add_node(lecturer2, type="Lecturer")
    G.add_node(lecturer3, type="Lecturer")
    G.add_node(model1, type="Concept")
    G.add_node(model2, type="Concept")
    
    # Add edges
    G.add_edge(pub1, lecturer1, label="HAS_AUTHOR")
    G.add_edge(pub1, lecturer2, label="HAS_AUTHOR")
    G.add_edge(pub1, lecturer3, label="HAS_AUTHOR")
    G.add_edge(pub1, model1, label="USES_MODEL")
    
    G.add_edge(pub2, lecturer2, label="HAS_AUTHOR")
    G.add_edge(pub2, lecturer3, label="HAS_AUTHOR")
    G.add_edge(pub2, model2, label="USES_MODEL")
    
    G.add_edge(lecturer1, lecturer2, label="COLLABORATES")
    G.add_edge(lecturer1, lecturer3, label="COLLABORATES")
    G.add_edge(lecturer2, lecturer3, label="COLLABORATES")

    plt.figure(figsize=(7, 6))
    
    # Closer positions to make the graph compact
    pos = {
        pub1: (-0.8, 0.5),
        pub2: (0.8, 0.5),
        model1: (-1.6, 1.2),
        model2: (1.6, 1.2),
        lecturer1: (-1.0, -0.6),
        lecturer2: (0, 0.0),
        lecturer3: (1.0, -0.6)
    }
    
    colors = {
        "Publication": "#3498db",  # Blue
        "Concept": "#e74c3c",      # Red
        "Lecturer": "#2ecc71"      # Green
    }
    
    for ntype, color in colors.items():
        nlist = [n for n, attr in G.nodes(data=True) if attr.get("type") == ntype]
        if nlist:
            nx.draw_networkx_nodes(G, pos, nodelist=nlist, node_color=color, node_size=7500, alpha=0.9)
        
    nx.draw_networkx_edges(G, pos, edgelist=G.edges(), width=2.5, arrowstyle="->", arrowsize=20, edge_color="#7f8c8d")
    
    labels = {
        pub1: "Implementing\nOptuna...",
        pub2: "Eksplorasi\nTeknik...",
        lecturer1: "R. C. Wibawa",
        lecturer2: "Achmad\nKautsar",
        lecturer3: "Yuni\nYamasari",
        model1: "CatBoost",
        model2: "XGBoost"
    }
    nx.draw_networkx_labels(G, pos, labels=labels, font_size=15, font_weight="bold")
    
    edge_labels = nx.get_edge_attributes(G, "label")
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=12)
    
    plt.axis("off")
    
    # Set limits manually with extra padding to prevent cropping of large node circles
    x_coords = [coords[0] for coords in pos.values()]
    y_coords = [coords[1] for coords in pos.values()]
    plt.xlim(min(x_coords) - 0.55, max(x_coords) + 0.55)
    plt.ylim(min(y_coords) - 0.55, max(y_coords) + 0.55)
    
    plt.tight_layout(pad=0.1)
    
    out_path = DOCS_GAMBAR_DIR / "sample_hybrid.png"
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print("[OK] Saved:", out_path)

if __name__ == "__main__":
    generate_subgraph_vis()
    generate_hybrid_vis()
