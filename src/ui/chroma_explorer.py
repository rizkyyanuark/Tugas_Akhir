import streamlit as st
import chromadb
import pandas as pd
import os

st.set_page_config(page_title="ChromaDB Explorer", layout="wide")

st.title("📂 ChromaDB Data Explorer")
st.markdown("Visualisasikan Koleksi dan Dokumen di dalam Vector Database lokal Anda.")

# Konfigurasi Path
CHROMA_PATH = "./notebooks/scraping/chroma_db"
if not os.path.exists(CHROMA_PATH):
    # Fallback to current dir if run from different location
    CHROMA_PATH = "./chroma_db"

st.sidebar.header("Konfigurasi")
path = st.sidebar.text_input("Path Ke Chroma DB", CHROMA_PATH)

if not os.path.exists(path):
    st.error(f"Path tidak ditemukan: {path}")
    st.stop()

try:
    client = chromadb.PersistentClient(path=path)
    collections = client.list_collections()
    
    if not collections:
        st.warning("Tidak ada koleksi yang ditemukan di path ini.")
        st.stop()

    coll_names = [c.name for c in collections]
    selected_coll = st.sidebar.selectbox("Pilih Koleksi", coll_names)

    if selected_coll:
        collection = client.get_collection(selected_coll)
        count = collection.count()
        
        st.subheader(f"Koleksi: `{selected_coll}`")
        st.info(f"Total Dokumen: **{count}**")

        if count > 0:
            # Pilihan untuk melihat data
            n_display = st.sidebar.number_input("Jumlah Data Ditampilkan", 1, count, min(10, count))
            
            data = collection.get(limit=n_display, include=['documents', 'metadatas', 'embeddings'])
            
            # Format ke DataFrame
            df_data = []
            for i in range(len(data['ids'])):
                row = {
                    "ID": data['ids'][i],
                    "Document": data['documents'][i][:500] + "..." if data['documents'][i] else "",
                }
                # Flatten metadatas
                if data['metadatas'] and data['metadatas'][i]:
                    for k, v in data['metadatas'][i].items():
                        row[f"Meta_{k}"] = v
                
                df_data.append(row)
            
            df = pd.DataFrame(df_data)
            st.dataframe(df, use_container_width=True)
            
            # Detail view
            st.divider()
            st.subheader("Detail Dokumen")
            selected_id = st.selectbox("Pilih ID untuk detail Lengkap", data['ids'])
            
            if selected_id:
                idx = data['ids'].index(selected_id)
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.text_area("Full Document", data['documents'][idx], height=300)
                
                with col2:
                    st.json(data['metadatas'][idx])
                    if data['embeddings']:
                        st.write("Embedding Vector Size:", len(data['embeddings'][idx]))
        else:
            st.write("Koleksi ini kosong.")

except Exception as e:
    st.error(f"Terjadi kesalahan saat menghubungkan ke ChromaDB: {e}")
