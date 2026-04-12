#!/usr/bin/env python3
"""Generate clean TTL files from NRC transcript text files - no multi-value syntax."""
import re
import os

TRANSCRIPTS = [
    {"file": "ML25322A364.txt", "date": "2025-11-18", "title": "Affirmation Session", "ml": "ML25322A364", "url": "https://www.nrc.gov/docs/ML2532/ML25322A364.pdf"},
    {"file": "ML25258A165.txt", "date": "2025-09-09", "title": "All Employees Meeting", "ml": "ML25258A165", "url": "https://www.nrc.gov/docs/ML2525/ML25258A165.pdf"},
    {"file": "ML25197A041.txt", "date": "2025-07-15", "title": "Affirmation Session", "ml": "ML25197A041", "url": "https://www.nrc.gov/docs/ML2519/ML25197A041.pdf"},
    {"file": "ML25174A277.txt", "date": "2025-06-17", "title": "Briefing on Human Capital and Equal Employment Opportunity", "ml": "ML25174A277", "url": "https://www.nrc.gov/docs/ML2517/ML25174A277.pdf"},
    {"file": "ML25139A570.txt", "date": "2025-05-13", "title": "Strategic Programmatic Overview of Fuel Facilities and Spent Fuel Storage and Transportation", "ml": "ML25139A570", "url": "https://www.nrc.gov/docs/ML2513/ML25139A570.pdf"},
    {"file": "ML25119A143.txt", "date": "2025-04-29", "title": "Affirmation Session", "ml": "ML25119A143", "url": "https://www.nrc.gov/docs/ML2511/ML25119A143.pdf"},
    {"file": "ML25104A260.txt", "date": "2025-04-10", "title": "Micro-reactors: Current Status and Moving Forward", "ml": "ML25104A260", "url": "https://www.nrc.gov/docs/ML2510/ML25104A260.pdf"},
    {"file": "ML25098A118.txt", "date": "2025-04-08", "title": "Affirmation Session", "ml": "ML25098A118", "url": "https://www.nrc.gov/docs/ML2509/ML25098A118.pdf"},
    {"file": "ML25104A265.txt", "date": "2025-04-08", "title": "Meeting with Advisory Committee on Medical Uses of Isotopes", "ml": "ML25104A265", "url": "https://www.nrc.gov/docs/ML2510/ML25104A265.pdf"},
    {"file": "ML25065A106.txt", "date": "2025-03-06", "title": "Affirmation Session", "ml": "ML25065A106", "url": "https://www.nrc.gov/docs/ML2506/ML25065A106.pdf"},
    {"file": "ML25066A005.txt", "date": "2025-03-04", "title": "Briefing on ADVANCE Act Activities", "ml": "ML25066A005", "url": "https://www.nrc.gov/docs/ML2506/ML25066A005.pdf"},
    {"file": "ML25017A206.txt", "date": "2025-01-14", "title": "Strategic Programmatic Overview of Decommissioning and Low-Level Waste and Nuclear Materials Users", "ml": "ML25017A206", "url": "https://www.nrc.gov/docs/ML2501/ML25017A206.pdf"},
]

BASE = "/tmp/nrc-transcripts"

def esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', '').strip()

def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def normalize_secy(raw):
    raw = raw.replace(' ', '')
    if re.match(r'SECY-\d{6,}', raw):
        return f"SECY-{raw[5:7]}-{raw[7:]}"
    parts = raw.split('-')
    if len(parts) == 3:
        return f"SECY-{parts[1]}-{parts[2].zfill(4)}"
    return raw

def get_meeting_id(date, title):
    ds = date.replace("-", "")
    if "Affirmation" in title: return f"meeting-affirm-{ds}"
    if "All Employees" in title: return f"meeting-aem-{ds}"
    if "Micro-reactor" in title.lower(): return f"meeting-microreactors-{ds}"
    if "ACMUI" in title or "Medical Uses" in title: return f"meeting-acmui-{ds}"
    if "ADVANCE Act" in title: return f"meeting-advance-act-{ds}"
    if "Human Capital" in title: return f"meeting-human-capital-{ds}"
    if "Fuel Facilit" in title or "Spent Fuel" in title: return f"meeting-fuel-overview-{ds}"
    if "Decommissioning" in title: return f"meeting-decomm-overview-{ds}"
    return f"meeting-{ds}"

def get_graph_name(date, title):
    ds = date.replace("-", "")
    slug = slugify(title[:40])
    return f"nrc-meeting-{ds}-{slug}"

def extract_people(text):
    people = {}
    header = text[:4000]
    
    # Match "Name, Chairman/Chair/Commissioner, presiding"
    for pattern in [
        r'(\w[\w.]+\s+\w[\w.]+(?:\s+\w[\w.]+)?),\s*(?:Chairman|Chair|Commissioner),?\s*presiding',
    ]:
        m = re.search(pattern, header)
        if m:
            name = m.group(1).strip()
            if name.isupper(): name = name.title()
            slug = slugify(name.split()[-1])
            people[slug] = {"name": name, "role": "Chairman", "chair": True}
            break
    
    for m in re.finditer(r'([A-Z][A-Z.\s]+?)(?:,\s*|\n\s*)(?:Member of the Commission|Commissioner)', header):
        raw = m.group(1).strip()
        raw = re.sub(r'\s+', ' ', raw)
        if 5 < len(raw) < 40 and not raw.startswith('ALSO'):
            name = raw.title()
            slug = slugify(name.split()[-1])
            if slug not in people:
                people[slug] = {"name": name, "role": "Commissioner", "chair": False}
    
    if re.search(r'CARRIE\s+(?:M\.\s+)?SAFFORD', header):
        people['safford'] = {"name": "Carrie M. Safford", "role": "Secretary of the Commission", "chair": False}
    
    gc = re.search(r'(BROOKE\s+CLARK|MARY\s+SPENCER)', header)
    if gc:
        name = gc.group(1).title()
        slug = slugify(name.split()[-1])
        people[slug] = {"name": name, "role": "General Counsel", "chair": False}
    
    return people

def process(t):
    with open(f"{BASE}/{t['file']}") as f:
        text = f.read()
    
    mid = get_meeting_id(t["date"], t["title"])
    url = t["url"]
    people = extract_people(text)
    
    triples = []  # list of (s, p, o) where o is either "literal" or <uri> or nrc:xxx
    
    def lit(s): return f'"{esc(s)}"^^xsd:string'
    def date_lit(s): return f'"{s}"^^xsd:date'
    def uri(s): return f'<{s}>'
    
    loc = "Rockville, Maryland (via teleconference)" if "teleconference" in text[:3000].lower() else "Rockville, Maryland"
    
    triples.append((f'nrc:{mid}', 'a', 'nrc:Meeting'))
    triples.append((f'nrc:{mid}', 'nrc:name', lit(t["title"])))
    triples.append((f'nrc:{mid}', 'nrc:date', date_lit(t["date"])))
    triples.append((f'nrc:{mid}', 'nrc:location', lit(loc)))
    triples.append((f'nrc:{mid}', 'prov:wasDerivedFrom', uri(url)))
    
    for slug, p in people.items():
        if p.get("chair"):
            triples.append((f'nrc:{mid}', 'nrc:chairedBy', f'nrc:person-{slug}'))
        else:
            triples.append((f'nrc:{mid}', 'nrc:attendedBy', f'nrc:person-{slug}'))
    
    for slug, p in people.items():
        triples.append((f'nrc:person-{slug}', 'a', 'nrc:Person'))
        triples.append((f'nrc:person-{slug}', 'nrc:name', lit(p["name"])))
        triples.append((f'nrc:person-{slug}', 'nrc:role', lit(p["role"])))
        triples.append((f'nrc:person-{slug}', 'nrc:affiliatedWith', 'nrc:org-nrc'))
        triples.append((f'nrc:person-{slug}', 'prov:wasDerivedFrom', uri(url)))
    
    triples.append(('nrc:org-nrc', 'a', 'nrc:Organization'))
    triples.append(('nrc:org-nrc', 'nrc:name', lit("U.S. Nuclear Regulatory Commission")))
    
    # Facilities
    fac_patterns = [
        (r'Diablo Canyon Nuclear Power Plant(?:, Units? \d(?: and \d)?)?', 'diablo-canyon'),
        (r'Palisades Nuclear Plant', 'palisades'),
        (r'Dewey-Burdock In Situ Uranium Recovery Facility', 'dewey-burdock'),
        (r'Indian Point Energy Center', 'indian-point'),
    ]
    for pattern, slug in fac_patterns:
        m = re.search(pattern, text)
        if m:
            triples.append((f'nrc:facility-{slug}', 'a', 'nrc:Facility'))
            triples.append((f'nrc:facility-{slug}', 'nrc:name', lit(m.group(0))))
            triples.append((f'nrc:facility-{slug}', 'prov:wasDerivedFrom', uri(url)))
    
    # Organizations
    org_patterns = [
        (r'Pacific Gas and Electric', 'pge', 'Pacific Gas and Electric Co.'),
        (r'Holtec', 'holtec', 'Holtec International'),
        (r'Entergy Nuclear', 'entergy', 'Entergy Nuclear Operations, Inc.'),
        (r'Westinghouse', 'westinghouse', 'Westinghouse Electric Company'),
        (r'Nuclear Energy Institute', 'nei', 'Nuclear Energy Institute'),
        (r'Department of Energy', 'doe', 'U.S. Department of Energy'),
        (r'Shepherd Power', 'shepherd-power', 'Shepherd Power'),
        (r'Powertech', 'powertech', 'Powertech (USA) Inc.'),
        (r'BWX Technologies|BWXT', 'bwxt', 'BWX Technologies'),
        (r'Kairos Power', 'kairos', 'Kairos Power'),
        (r'X-energy', 'x-energy', 'X-energy'),
        (r'Oklo', 'oklo', 'Oklo Inc.'),
        (r'NuScale', 'nuscale', 'NuScale Power'),
    ]
    for pattern, slug, name in org_patterns:
        if re.search(pattern, text):
            triples.append((f'nrc:org-{slug}', 'a', 'nrc:Organization'))
            triples.append((f'nrc:org-{slug}', 'nrc:name', lit(name)))
            triples.append((f'nrc:org-{slug}', 'prov:wasDerivedFrom', uri(url)))
    
    # Affirmation decisions
    if "Affirmation" in t["title"]:
        decisions = []
        for m in re.finditer(r"item(?:,| is)\s+(SECY[-\s]?\d{2}[-\s]?\d{3,4})\s*[-–—]\s*(.+?)(?:\.\s+The Commission|\.\s+Would|\.\s+This)", text, re.DOTALL):
            secy = normalize_secy(m.group(1))
            title_text = re.sub(r'\s+', ' ', m.group(2).strip())
            decisions.append({"secy": secy, "title": title_text})
        
        outcomes = list(re.finditer(r"Commission has voted to\s+(.+?)(?:\.\s)", text))
        for i, m in enumerate(outcomes):
            if i < len(decisions):
                decisions[i]["outcome"] = re.sub(r'\s+', ' ', m.group(1).strip())
        
        ds = t["date"].replace("-", "")
        for i, dec in enumerate(decisions):
            secy_slug = slugify(dec["secy"])
            doc_id = f"doc-{secy_slug}"
            item_id = f"item-{ds}-{i+1}"
            dec_id = f"decision-{ds}-{i+1}"
            
            triples.append((f'nrc:{doc_id}', 'a', 'nrc:RegulatoryDocument'))
            triples.append((f'nrc:{doc_id}', 'nrc:secyNumber', lit(dec["secy"])))
            triples.append((f'nrc:{doc_id}', 'nrc:title', lit(dec["title"])))
            triples.append((f'nrc:{doc_id}', 'prov:wasDerivedFrom', uri(url)))
            
            triples.append((f'nrc:{item_id}', 'a', 'nrc:AgendaItem'))
            triples.append((f'nrc:{item_id}', 'nrc:itemNumber', str(i+1)))
            triples.append((f'nrc:{item_id}', 'nrc:concerns', f'nrc:{doc_id}'))
            triples.append((f'nrc:{item_id}', 'nrc:resultedIn', f'nrc:{dec_id}'))
            triples.append((f'nrc:{item_id}', 'prov:wasDerivedFrom', uri(url)))
            
            triples.append((f'nrc:{mid}', 'nrc:hasAgendaItem', f'nrc:{item_id}'))
            
            outcome = dec.get("outcome", "Approved")
            triples.append((f'nrc:{dec_id}', 'a', 'nrc:Decision'))
            triples.append((f'nrc:{dec_id}', 'nrc:description', lit(outcome)))
            triples.append((f'nrc:{dec_id}', 'nrc:outcome', lit(outcome)))
            
            for slug, p in people.items():
                if p["role"] in ("Chairman", "Commissioner"):
                    triples.append((f'nrc:{dec_id}', 'nrc:votedBy', f'nrc:person-{slug}'))
    
    # SECY refs for non-affirmation meetings
    elif len(text) > 1000:
        secys = set()
        for m in re.finditer(r'SECY[-\s]?\d{2}[-\s]?\d{3,4}', text):
            secys.add(normalize_secy(m.group(0)))
        for secy in sorted(secys):
            secy_slug = slugify(secy)
            doc_id = f"doc-{secy_slug}"
            triples.append((f'nrc:{doc_id}', 'a', 'nrc:RegulatoryDocument'))
            triples.append((f'nrc:{doc_id}', 'nrc:secyNumber', lit(secy)))
            triples.append((f'nrc:{doc_id}', 'prov:wasDerivedFrom', uri(url)))
    
    # Now serialize as clean TTL - one statement per line
    lines = [
        '@prefix nrc: <http://example.com/nrc#> .',
        '@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .',
        '@prefix prov: <http://www.w3.org/ns/prov#> .',
        '',
    ]
    
    # Group by subject for readability
    from collections import OrderedDict
    subjects = OrderedDict()
    for s, p, o in triples:
        subjects.setdefault(s, []).append((p, o))
    
    for s, props in subjects.items():
        lines.append(f'{s}')
        for i, (p, o) in enumerate(props):
            sep = ' ;' if i < len(props) - 1 else ' .'
            lines.append(f'    {p} {o}{sep}')
        lines.append('')
    
    outpath = f"{BASE}/{t['ml']}.ttl"
    with open(outpath, 'w') as f:
        f.write('\n'.join(lines))
    
    return outpath, get_graph_name(t["date"], t["title"])


if __name__ == "__main__":
    for t in TRANSCRIPTS:
        outpath, graph = process(t)
        print(f"{graph}\t{outpath}\t{t['date']}\t{t['title']}")
