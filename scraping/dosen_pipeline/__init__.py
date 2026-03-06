"""
UNESA Dosen Data Pipeline with Professional Data Engineering Logging

A multi-source data integration pipeline for lecturer information from:
- PDDIKTI API (national higher education database)
- University department websites (10 prodi)
- SimCV (NIP/NIDN enrichment)
- SINTA (research metrics)
- SciVal/Scopus (publication data)
- Google Scholar (verification)

Features:
- Comprehensive logging with loguru (console + file)
- Data quality metrics tracking at each phase
- Performance monitoring with bottleneck detection
- Fuzzy name matching with audit trails
- CLI interface with flexible execution modes
"""

__version__ = "3.0.0"
__author__ = "Refactored for Professional Data Engineering"
