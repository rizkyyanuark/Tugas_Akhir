import sys
import os
import pandas as pd
from pathlib import Path

sys.path.insert(0, "/opt/airflow")

from src.etl.transform.cleaner import clean_papers_batch

def test_multi_author_id():
    # Mock data based on the user's image (Row 1)
    # Authors: Yuni Yamasari; Anita Qoiriah; Ricky Eka Putra; Agus Prihanto; I Made Suartana; Aditya Prapanca
    # Initial ID: WdhKN0sAAAAJ (which belongs to Aditya Prapanca)
    test_data = [
        {
            "Title": "Test Multi-Author ID Paper",
            "Authors": "Yuni Yamasari, Anita Qoiriah, Ricky Eka Putra, Agus Prihanto, I Made Suartana, Aditya Prapanca",
            "Author IDs": "WdhKN0sAAAAJ",
            "Year": "2025",
            "source": "scholar",
        }
    ]
    
    df = pd.DataFrame(test_data)
    print("INPUT RAW DATA:")
    print(f"Authors: {df.iloc[0]['Authors']}")
    print(f"Raw IDs: {df.iloc[0]['Author IDs']}")
    
    df_cleaned = clean_papers_batch(df)
    
    print("\nOUTPUT CLEANED DATA:")
    print(f"Authors: {df_cleaned.iloc[0]['Authors']}")
    print(f"Final IDs: {df_cleaned.iloc[0]['Author IDs']}")
    
    # Validation
    final_ids = df_cleaned.iloc[0]['Author IDs'].split(';')
    print(f"\nNumber of IDs found: {len(final_ids)}")
    
    if len(final_ids) == 6:
        print("✅ SUCCESS: All 6 authors got their IDs!")
    else:
        print(f"❌ FAILURE: Only {len(final_ids)} authors got IDs.")

if __name__ == "__main__":
    test_multi_author_id()
