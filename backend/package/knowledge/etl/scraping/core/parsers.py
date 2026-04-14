# scraping_modules/parsers.py
# NOTE: Web parsers only extract NIP + scholar_id.
# scopus_id comes from SciVal, sinta_id comes from SINTA crawler.
import re
from knowledge.etl.scraping.utils import extract_ids_from_links, make_entry

def parse_table_standard(soup):
    """Parses standard HTML tables (e.g. TI, SI)."""
    results = []
    for tr in soup.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 3: continue
        name_txt = tds[1].get_text(strip=True) if len(tds) > 1 else ''
        nip_txt = tds[2].get_text(strip=True) if len(tds) > 2 else ''
        if not name_txt or len(name_txt) < 4: continue
        if name_txt.lower() in ['name', 'nama', 'nama dosen']: continue
        
        nip_m = re.search(r'(\d{9,})', nip_txt)
        nip = nip_m.group(1) if nip_m else None
        
        scholar, _scopus, _sinta, cv_nip = extract_ids_from_links(tr.find_all('a', href=True))
        if not nip and cv_nip: nip = cv_nip
        
        results.append(make_entry(name_txt, nip=nip, scholar=scholar))
    return results

def parse_pendti(soup):
    """Parses Pendidikan TI website."""
    results = []
    for tr in soup.find_all('tr'):
        tds = tr.find_all('td')
        if len(tds) < 3: continue
        name_txt = tds[1].get_text(strip=True)
        nip_txt = tds[2].get_text(strip=True)
        if not name_txt or name_txt.lower() in ['name', 'nama']: continue
        if len(name_txt) < 4: continue
        
        nip_m = re.search(r'(\d{9,})', nip_txt)
        nip = nip_m.group(1) if nip_m else None
        
        links_td = tds[3] if len(tds) > 3 else tr
        scholar, _scopus, _sinta, cv_nip = extract_ids_from_links(links_td.find_all('a', href=True))
        if not nip and cv_nip: nip = cv_nip
        
        results.append(make_entry(name_txt, nip=nip, scholar=scholar))
    return results

def parse_elektro(soup):
    """Parses Teknik Elektro website (Grid layout)."""
    results = []
    seen = set()
    tables = soup.find_all('table', class_='MsoTableGrid')
    if not tables: tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2: continue
        first_row_tds = rows[0].find_all('td')
        names = []
        for td in first_row_tds:
            txt = td.get_text(strip=True)
            if len(txt)>5 and not re.match(r'^\d+$', txt) and not any(x in txt.lower() for x in ['sinta','scopus']):
                names.append(txt)
                
        id_cols = [1, 3] # Assumed column indices for ID data
        for i, name in enumerate(names):
            if name in seen: continue
            seen.add(name)
            nip = scholar = None
            col_idx = id_cols[i] if i < len(id_cols) else None
            if col_idx is None: continue
            
            for row in rows[1:]:
                tds = row.find_all('td')
                if col_idx >= len(tds): continue
                cell = tds[col_idx]
                label = tds[col_idx-1].get_text(strip=True).lower() if col_idx>0 else ''
                
                # Only extract scholar_id and NIP from web
                if 'scholar' in label:
                    s,_,_,_ = extract_ids_from_links(cell.find_all('a',href=True))
                    if s: scholar = s
                elif 'cv' in label:
                    _,_,_,n = extract_ids_from_links(cell.find_all('a',href=True))
                    if n: nip = n

            results.append(make_entry(name, nip=nip, scholar=scholar))
    return results

def parse_simcv(soup):
    """
    Parser for D4 Manajemen Informatika & SimCV-based pages.
    """
    results = []
    seen_nips = set()
    
    links = soup.find_all('a', href=lambda h: h and 'cv.unesa.ac.id' in h)
    
    for link in links:
        m = re.search(r'detail/(\d+)', link.get('href',''))
        nip = m.group(1) if m else None
        
        if nip and nip in seen_nips: continue
        if nip: seen_nips.add(nip)
        
        container = link.find_parent('td') or link.parent
        scholar, _scopus, _sinta, cv_nip = extract_ids_from_links(container.find_all('a', href=True))
        if not nip: nip = cv_nip
        
        name = None
        for tag in ['h1','h2','h3','h4', 'h5', 'strong', 'b']:
            for h in container.find_all(tag):
                t = h.get_text(separator=' ', strip=True)
                t = re.sub(r'\s+', ' ', t).strip() 
                
                if len(t) > 3 and not re.match(r'^[\d\W]+$', t) and 'nama' not in t.lower():
                    if t.lower() not in ['dosen', 'profil', 'dr.', 'prof.']:
                        name = t
                        break
            if name: break
            
        if name:
            results.append(make_entry(name, nip=nip, scholar=scholar))
    return results

def parse_sains_data(soup):
    """Parses Sains Data website."""
    results = []
    for div in soup.find_all('div', class_='nama-dosen'):
        name = div.get_text(strip=True)
        container = div.find_parent('td') or div.parent
        scholar, _scopus, _sinta, nip = extract_ids_from_links(container.find_all('a', href=True))
        results.append(make_entry(name, nip=nip, scholar=scholar))
    return results

def parse_bisdig(soup):
    """Parses Bisnis Digital website."""
    results = []
    seen = set()
    for h3 in soup.find_all('h3'):
        name = h3.get_text(strip=True)
        if len(name)<5 or name in seen or 'dosen' in name.lower(): continue
        seen.add(name)
        
        container = h3.parent
        scholar, _scopus, _sinta, nip = extract_ids_from_links(container.find_all('a', href=True))
        if not nip:
            p = container.find('p', string=re.compile(r'NIP'))
            if p: 
                m = re.search(r'(\d{9,})', p.get_text())
                if m: nip = m.group(1)
        
        results.append(make_entry(name, nip=nip, scholar=scholar))
    return results

def parse_s2if(soup):
    """Parses S2 Informatika (Card Layout)."""
    results = []
    seen = set()
    
    anchors = soup.find_all('a', href=lambda h: h and ('scholar.google' in h or 'scopus' in h))
    for a in anchors:
        container = a.find_parent('div', class_=re.compile(r'row|col|card|team')) or a.parent.parent
        
        name = ""
        for tag in ['h3', 'h4', 'h5', 'strong', 'b']:
            t = container.find(tag)
            if t and len(t.get_text(strip=True)) > 3:
                name = t.get_text(strip=True)
                break
        
        if name and name not in seen:
            seen.add(name)
            scholar, _scopus, _sinta, nip = extract_ids_from_links(container.find_all('a', href=True))
            results.append(make_entry(name, nip=nip, scholar=scholar))
            
    if not results:
         for h in soup.find_all(['h4', 'h5']):
             name = h.get_text(strip=True)
             if len(name) > 5 and 'dosen' not in name.lower():
                 parent = h.parent
                 scholar, _scopus, _sinta, nip = extract_ids_from_links(parent.find_all('a', href=True))
                 results.append(make_entry(name, nip=nip, scholar=scholar))
    return results

def parse_s2pti(soup):
    """Parses S2 PTI (Table with Header checks)."""
    results = []
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) < 2: continue 
        
        for tr in rows:
            row_txt = tr.get_text(" ", strip=True).lower()
            if 'profil' in row_txt and 'keterangan' in row_txt: continue
            if 'nama dosen' in row_txt: continue
            
            nip, nidn = None, None
            m_nip = re.search(r'\b((?:19|20)\d{16})\b', row_txt)
            if m_nip: nip = m_nip.group(1)
            m_nidn = re.search(r'\b(0\d{9})\b', row_txt)
            if m_nidn: nidn = m_nidn.group(1)
            
            tds = tr.find_all('td')
            name = ""
            max_len = 0
            for td in tds:
                txt = td.get_text(strip=True)
                if len(txt) > 3 and not re.match(r'^[\d\W]+$', txt) and 'nama' not in txt.lower():
                    clean_txt = re.sub(r'(NIP|NIDN|Email).*', '', txt, flags=re.IGNORECASE).strip()
                    clean_txt = re.sub(r'\d{18}', '', clean_txt).strip()
                    
                    if len(clean_txt) > max_len:
                        max_len = len(clean_txt)
                        name = clean_txt
            
            scholar, _scopus, _sinta, cv_nip = extract_ids_from_links(tr.find_all('a', href=True))
            if not nip and cv_nip: nip = cv_nip
            
            if name:
                 results.append(make_entry(name, nip=nip, nidn=nidn, scholar=scholar))
    return results

# PARSER STRATEGY MAP
PARSER_MAP = {
    'table': parse_table_standard,
    'pendti': parse_pendti,
    'te': parse_elektro,
    'simcv': parse_simcv,
    'sains': parse_sains_data,
    'bisdig': parse_bisdig,
    's2if': parse_s2if,
    's2pti': parse_s2pti
}
