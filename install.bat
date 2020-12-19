pip install -r requirements.txt
nssm install manga_tagger "C:\Manga Tagger\run.bat"
nssm set manga_tagger AppDirectory "C:\Manga Tagger"
nssm set manga_tagger AppExit Default Restart
nssm set manga_tagger Description "A tool to rename and tag downloaded manga chapters with scraped metadata"
nssm set manga_tagger DisplayName "Manga Tagger"
nssm set manga_tagger ObjectName LocalSystem
nssm set manga_tagger Start SERVICE_AUTO_START
nssm set manga_tagger Type SERVICE_WIN32_OWN_PROCESS
