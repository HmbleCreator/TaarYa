import matplotlib.pyplot as plt
import networkx as nx

def generate_architecture_diagram():
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Define layers and their components
    layers = {
        "Interoperability": ["SAMP Hub", "VOTable Export", "REST API"],
        "Agentic Core": ["LangChain Orchestrator", "Semantic Summarizer"],
        "Hybrid Engines": ["Q3C Spatial (PostgreSQL)", "Qdrant Semantic", "Neo4j Graph"],
        "Science Layer": ["Discovery Scoring", "Uncertainty Prop.", "Extinction Correction"]
    }
    
    # Define positions
    pos = {}
    layer_names = list(layers.keys())
    for i, layer in enumerate(layer_names):
        components = layers[layer]
        for j, comp in enumerate(components):
            pos[comp] = (i * 3, -j * 1.5)
            
    # Create Graph
    G = nx.DiGraph()
    for i in range(len(layer_names) - 1):
        for c1 in layers[layer_names[i]]:
            for c2 in layers[layer_names[i+1]]:
                G.add_edge(c1, c2)
                
    # Draw Nodes
    for layer, components in layers.items():
        nx.draw_networkx_nodes(G, pos, nodelist=components, 
                               node_color='skyblue', node_size=3000, 
                               alpha=0.8, edgecolors='navy')
        
    # Draw Edges
    nx.draw_networkx_edges(G, pos, width=1.5, alpha=0.3, edge_color='gray', 
                           arrowsize=20, connectionstyle='arc3,rad=0.1')
    
    # Draw Labels
    nx.draw_networkx_labels(G, pos, font_size=8, font_family='sans-serif', font_weight='bold')
    
    # Add Layer Titles
    for i, layer in enumerate(layer_names):
        plt.text(i * 3, 1.0, layer, fontsize=12, fontweight='bold', ha='center', color='darkred')
        
    plt.title("TaarYa System Architecture", fontsize=16, pad=20)
    plt.axis('off')
    plt.tight_layout()
    plt.savefig("taarya_architecture.png", dpi=300)
    print("Architecture diagram saved as taarya_architecture.png")

if __name__ == "__main__":
    generate_architecture_diagram()
