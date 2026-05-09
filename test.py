from MediaTools.MediaDownloader import MediaDownloader

downloader = MediaDownloader()
# 隨便搜尋一首歌來觸發 yt-dlp 的驗證機制
downloader.search_and_download_audio("Sia Snowman")