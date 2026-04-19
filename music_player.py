import sys
import os
import json
import base64
import vlc
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl, QTimer

# Instructions for Arch/Manjaro:
# sudo pacman -S vlc
# pip install PyQt6 PyQt6-WebEngine python-vlc mutagen

class PlayerBridge(QObject):
    # Signals to send data to JS
    updateStatus = pyqtSignal(str)
    trackEnded = pyqtSignal()
    updatePosition = pyqtSignal(float, float) # current, duration

    def __init__(self, player_ctrl):
        super().__init__()
        self.player_ctrl = player_ctrl

    @pyqtSlot()
    def openFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select Music Folder")
        if folder:
            self.player_ctrl.load_folder(folder)

    @pyqtSlot(str)
    def playTrack(self, filepath):
        self.player_ctrl.play(filepath)

    @pyqtSlot()
    def togglePause(self):
        self.player_ctrl.toggle_pause()

    @pyqtSlot(float)
    def setPosition(self, percent):
        self.player_ctrl.set_position(percent)

    @pyqtSlot(float)
    def setVolume(self, volume):
        self.player_ctrl.set_volume(int(volume * 100))

    @pyqtSlot(str, str)
    def saveMetadata(self, filepath, metadata_json):
        metadata = json.loads(metadata_json)
        self.player_ctrl.save_metadata(filepath, metadata)

class PlayerController:
    def __init__(self, bridge):
        self.bridge = bridge
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.update_pos)
        self.timer.start()

        self.current_file = None

        # VLC Events
        self.event_manager = self.player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_end)

    def load_folder(self, folder):
        tracks = []
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(('.mp3', '.flac', '.ogg', '.wav')):
                    path = os.path.join(root, file)
                    tracks.append(self.get_metadata(path))

        self.bridge.updateStatus.emit(json.dumps({'type': 'library', 'tracks': tracks}))

    def get_metadata(self, path):
        meta = {
            'path': path,
            'title': os.path.basename(path),
            'artist': 'Unknown Artist',
            'album': 'Unknown Album',
            'year': '',
            'genre': '',
            'cover': None
        }
        try:
            audio = mutagen.File(path)
            if audio:
                if isinstance(audio, MP3):
                    if audio.tags:
                        meta['title'] = str(audio.tags.get('TIT2', meta['title']))
                        meta['artist'] = str(audio.tags.get('TPE1', 'Unknown Artist'))
                        meta['album'] = str(audio.tags.get('TALB', 'Unknown Album'))
                        meta['year'] = str(audio.tags.get('TDRC', ''))
                        meta['genre'] = str(audio.tags.get('TCON', ''))
                        for tag in audio.tags.values():
                            if isinstance(tag, APIC):
                                meta['cover'] = f"data:{tag.mime};base64,{base64.b64encode(tag.data).decode()}"
                                break
                elif isinstance(audio, FLAC):
                    meta['title'] = audio.get('title', [meta['title']])[0]
                    meta['artist'] = audio.get('artist', ['Unknown Artist'])[0]
                    meta['album'] = audio.get('album', ['Unknown Album'])[0]
                    meta['year'] = audio.get('date', [''])[0]
                    meta['genre'] = audio.get('genre', [''])[0]
                    if audio.pictures:
                        p = audio.pictures[0]
                        meta['cover'] = f"data:{p.mime};base64,{base64.b64encode(p.data).decode()}"
                elif isinstance(audio, OggVorbis):
                    meta['title'] = audio.get('title', [meta['title']])[0]
                    meta['artist'] = audio.get('artist', ['Unknown Artist'])[0]
                    meta['album'] = audio.get('album', ['Unknown Album'])[0]
                    meta['year'] = audio.get('date', [''])[0]
                    meta['genre'] = audio.get('genre', [''])[0]
                    if 'metadata_block_picture' in audio:
                        for b64_data in audio['metadata_block_picture']:
                            try:
                                p = Picture(base64.b64decode(b64_data))
                                meta['cover'] = f"data:{p.mime};base64,{base64.b64encode(p.data).decode()}"
                                break
                            except: continue
                elif isinstance(audio, WAVE):
                    if audio.tags:
                        meta['title'] = str(audio.tags.get('TIT2', meta['title']))
                        meta['artist'] = str(audio.tags.get('TPE1', 'Unknown Artist'))
                        meta['album'] = str(audio.tags.get('TALB', 'Unknown Album'))
                        meta['year'] = str(audio.tags.get('TDRC', ''))
                        meta['genre'] = str(audio.tags.get('TCON', ''))
                        for tag in audio.tags.values():
                            if isinstance(tag, APIC):
                                meta['cover'] = f"data:{tag.mime};base64,{base64.b64encode(tag.data).decode()}"
                                break
        except Exception as e:
            print(f"Error reading metadata for {path}: {e}")
        return meta

    def play(self, path):
        self.current_file = path
        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()

    def toggle_pause(self):
        self.player.pause()

    def set_position(self, percent):
        self.player.set_position(percent)

    def set_volume(self, volume):
        self.player.audio_set_volume(volume)

    def update_pos(self):
        if self.player.is_playing():
            pos = self.player.get_position()
            time = self.player.get_time() / 1000
            duration = self.player.get_length() / 1000
            self.bridge.updatePosition.emit(time, duration)

    def on_end(self, event):
        self.bridge.trackEnded.emit()

    def save_metadata(self, path, meta):
        try:
            audio = mutagen.File(path)
            if isinstance(audio, MP3):
                if audio.tags is None: audio.add_tags()
                audio.tags.add(TIT2(encoding=3, text=meta['title']))
                audio.tags.add(TPE1(encoding=3, text=meta['artist']))
                audio.tags.add(TALB(encoding=3, text=meta['album']))
                audio.tags.add(TDRC(encoding=3, text=meta['year']))
                audio.tags.add(TCON(encoding=3, text=meta['genre']))
                if 'cover_base64' in meta and meta['cover_base64']:
                    header, encoded = meta['cover_base64'].split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    data = base64.b64decode(encoded)
                    audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=data))
                audio.save()
            elif isinstance(audio, FLAC):
                audio['title'] = meta['title']
                audio['artist'] = meta['artist']
                audio['album'] = meta['album']
                audio['date'] = meta['year']
                audio['genre'] = meta['genre']
                if 'cover_base64' in meta and meta['cover_base64']:
                    header, encoded = meta['cover_base64'].split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    data = base64.b64decode(encoded)
                    p = Picture()
                    p.data = data
                    p.mime = mime
                    p.type = 3
                    audio.clear_pictures()
                    audio.add_picture(p)
                audio.save()
            elif isinstance(audio, OggVorbis):
                audio['title'] = meta['title']
                audio['artist'] = meta['artist']
                audio['album'] = meta['album']
                audio['date'] = meta['year']
                audio['genre'] = meta['genre']
                if 'cover_base64' in meta and meta['cover_base64']:
                    header, encoded = meta['cover_base64'].split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    data = base64.b64decode(encoded)
                    p = Picture()
                    p.data = data
                    p.mime = mime
                    p.type = 3
                    audio.clear_pictures()
                    audio.add_picture(p)
                audio.save()
            elif isinstance(audio, WAVE):
                if audio.tags is None: audio.add_tags()
                audio.tags.add(TIT2(encoding=3, text=meta['title']))
                audio.tags.add(TPE1(encoding=3, text=meta['artist']))
                audio.tags.add(TALB(encoding=3, text=meta['album']))
                audio.tags.add(TDRC(encoding=3, text=meta['year']))
                audio.tags.add(TCON(encoding=3, text=meta['genre']))
                if 'cover_base64' in meta and meta['cover_base64']:
                    header, encoded = meta['cover_base64'].split(",", 1)
                    mime = header.split(":")[1].split(";")[0]
                    data = base64.b64decode(encoded)
                    audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=data))
                audio.save()
            # Reload metadata in UI
            new_meta = self.get_metadata(path)
            self.bridge.updateStatus.emit(json.dumps({'type': 'metadata_update', 'track': new_meta}))
        except Exception as e:
            print(f"Error saving metadata: {e}")

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <style>
        :root {
            --bg-color: #0f0f0f;
            --sidebar-color: #161616;
            --accent-color: #1db954; /* Spotify-ish green, or Manjaro #16a085 */
            --manjaro-green: #16a085;
            --text-main: #ffffff;
            --text-dim: #b3b3b3;
            --glass: rgba(255, 255, 255, 0.05);
            --border: 1px solid rgba(255, 255, 255, 0.1);
        }

        body {
            margin: 0;
            padding: 0;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .layout {
            display: flex;
            flex: 1;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 280px;
            background-color: var(--sidebar-color);
            display: flex;
            flex-direction: column;
            border-right: var(--border);
        }

        .sidebar-header {
            padding: 24px;
        }

        .btn-open {
            background-color: var(--manjaro-green);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            width: 100%;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-open:hover {
            transform: translateY(-2px);
            filter: brightness(1.1);
        }

        .playlist {
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }

        .track-item {
            display: flex;
            align-items: center;
            padding: 8px;
            border-radius: 6px;
            cursor: pointer;
            margin-bottom: 4px;
            transition: background 0.2s;
        }

        .track-item:hover {
            background: var(--glass);
        }

        .track-item.active {
            background: rgba(22, 160, 133, 0.2);
            border-left: 3px solid var(--manjaro-green);
        }

        .track-thumb {
            width: 40px;
            height: 40px;
            border-radius: 4px;
            background: #222;
            margin-right: 12px;
            object-fit: cover;
        }

        .track-info {
            flex: 1;
            overflow: hidden;
        }

        .track-title {
            font-size: 0.9rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .track-artist {
            font-size: 0.75rem;
            color: var(--text-dim);
        }

        /* Main View */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: linear-gradient(180deg, #1a1a1a 0%, #0f0f0f 100%);
            padding: 40px;
            position: relative;
        }

        .now-playing-card {
            width: 100%;
            max-width: 500px;
            text-align: center;
        }

        .album-art-wrap {
            width: 350px;
            height: 350px;
            margin: 0 auto 32px;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6);
            background: #222;
        }

        .album-art-wrap img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .current-title {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .current-artist {
            font-size: 1.2rem;
            color: var(--text-dim);
            margin-bottom: 24px;
        }

        /* Footer / Controls */
        .footer {
            height: 110px;
            background: var(--sidebar-color);
            border-top: var(--border);
            display: flex;
            align-items: center;
            padding: 0 32px;
            gap: 40px;
        }

        .playback-btns {
            display: flex;
            align-items: center;
            gap: 24px;
        }

        .icon-btn {
            background: none;
            border: none;
            color: var(--text-main);
            cursor: pointer;
            padding: 8px;
            border-radius: 50%;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .icon-btn:hover {
            background: var(--glass);
            color: var(--manjaro-green);
        }

        .play-pause-btn {
            width: 56px;
            height: 56px;
            background: white;
            color: black;
        }

        .play-pause-btn:hover {
            transform: scale(1.05);
            background: white;
            color: var(--manjaro-green);
        }

        .progress-section {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .time-labels {
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-dim);
            font-variant-numeric: tabular-nums;
        }

        .slider-wrap {
            height: 4px;
            background: #333;
            border-radius: 2px;
            cursor: pointer;
            position: relative;
        }

        .slider-bar {
            height: 100%;
            background: var(--manjaro-green);
            border-radius: 2px;
            width: 0%;
        }

        .volume-section {
            width: 150px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        input[type="range"] {
            flex: 1;
            accent-color: var(--manjaro-green);
        }

        /* Modal */
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(10px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal-content {
            background: #1e1e1e;
            padding: 32px;
            border-radius: 16px;
            width: 400px;
            border: var(--border);
        }

        .input-group {
            margin-bottom: 16px;
        }

        .input-group label {
            display: block;
            font-size: 0.8rem;
            color: var(--text-dim);
            margin-bottom: 6px;
        }

        .input-group input {
            width: 100%;
            background: #2a2a2a;
            border: var(--border);
            padding: 10px;
            color: white;
            border-radius: 6px;
            box-sizing: border-box;
        }

        .modal-footer {
            display: flex;
            gap: 12px;
            margin-top: 24px;
        }

        .btn-secondary {
            background: transparent;
            color: white;
            border: var(--border);
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            flex: 1;
        }

        /* SVG Icons */
        svg {
            width: 24px;
            height: 24px;
            fill: currentColor;
        }

        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #444; }
    </style>
</head>
<body>
    <div class="layout">
        <div class="sidebar">
            <div class="sidebar-header">
                <button class="btn-open" onclick="bridge.openFolder()">Open Folder</button>
            </div>
            <div class="playlist" id="playlist">
                <!-- Tracks here -->
            </div>
        </div>
        <div class="main">
            <div class="now-playing-card">
                <div class="album-art-wrap">
                    <img id="main-art" src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiM0NDQiIHN0cm9rZS13aWR0aD0iMSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNOSAxOGgyYTIgMiAwIDAgMCAyLTJWNSIvPjxwYXRoIGQ9Ik05IDE4YTkgOSAwIDEgMSAxOCAwIDkgOSAwIDAgMS0xOCAwWiIvPjxjaXJjbGUgY3g9IjciIGN5PSIxOCIgcj0iMyIvPjwvc3ZnPg==" alt="">
                </div>
                <div class="current-title" id="main-title">No track selected</div>
                <div class="current-artist" id="main-artist">Select a folder to start listening</div>
                <button class="btn-secondary" onclick="openMetaModal()">Edit Metadata</button>
            </div>
        </div>
    </div>

    <div class="footer">
        <div class="playback-btns">
            <button class="icon-btn" onclick="playPrev()">
                <svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z"/></svg>
            </button>
            <button class="icon-btn play-pause-btn" onclick="bridge.togglePause()">
                <svg id="play-icon" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                <svg id="pause-icon" viewBox="0 0 24 24" style="display:none"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
            </button>
            <button class="icon-btn" onclick="playNext()">
                <svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>
            </button>
        </div>

        <div class="progress-section">
            <div class="slider-wrap" id="seek-wrap" onclick="seek(event)">
                <div class="slider-bar" id="seek-bar"></div>
            </div>
            <div class="time-labels">
                <span id="cur-time">0:00</span>
                <span id="dur-time">0:00</span>
            </div>
        </div>

        <div class="volume-section">
            <svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>
            <input type="range" min="0" max="1" step="0.01" value="0.7" oninput="bridge.setVolume(this.value)">
        </div>
    </div>

    <div class="modal" id="meta-modal">
        <div class="modal-content">
            <h2 style="margin-top:0">Edit Metadata</h2>
            <div class="input-group">
                <label>Title</label>
                <input type="text" id="meta-title">
            </div>
            <div class="input-group">
                <label>Artist</label>
                <input type="text" id="meta-artist">
            </div>
            <div class="input-group">
                <label>Album</label>
                <input type="text" id="meta-album">
            </div>
            <div class="input-group">
                <label>Year</label>
                <input type="text" id="meta-year">
            </div>
            <div class="input-group">
                <label>Genre</label>
                <input type="text" id="meta-genre">
            </div>
            <div class="input-group">
                <label>Custom Cover</label>
                <input type="file" id="meta-cover-input" accept="image/*">
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeMetaModal()">Cancel</button>
                <button class="btn-open" onclick="saveMeta()">Save Changes</button>
            </div>
        </div>
    </div>

    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        let bridge;
        let library = [];
        let currentIndex = -1;
        const defaultArt = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiM0NDQiIHN0cm9rZS13aWR0aD0iMSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNOSAxOGgyYTIgMiAwIDAgMCAyLTJWNSIvPjxwYXRoIGQ9Ik05IDE4YTkgOSAwIDEgMSAxOCAwIDkgOSAwIDAgMS0xOCAwWiIvPjxjaXJjbGUgY3g9IjciIGN5PSIxOCIgcj0iMyIvPjwvc3ZnPg==';

        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;

            // Handle togglePause manually to ensure UI sync
            window.togglePause = function() {
                const isPaused = document.getElementById('play-icon').style.display === 'block';
                updatePlayPauseUI(isPaused);
                bridge.togglePause();
            };

            bridge.updateStatus.connect(function (status) {
                const data = JSON.parse(status);
                if (data.type === 'library') {
                    library = data.tracks;
                    renderLibrary();
                } else if (data.type === 'metadata_update') {
                    const idx = library.findIndex(t => t.path === data.track.path);
                    if (idx !== -1) {
                        library[idx] = data.track;
                        renderLibrary();
                        if (currentIndex === idx) updateDisplay();
                    }
                }
            });

            bridge.updatePosition.connect(function (cur, dur) {
                document.getElementById('cur-time').textContent = formatTime(cur);
                document.getElementById('dur-time').textContent = formatTime(dur);
                document.getElementById('seek-bar').style.width = (cur / dur * 100) + '%';
            });

            bridge.trackEnded.connect(playNext);
        });

        function renderLibrary() {
            const container = document.getElementById('playlist');
            container.innerHTML = library.map((t, i) => `
                <div class="track-item ${i === currentIndex ? 'active' : ''}" onclick="selectTrack(${i})">
                    <img class="track-thumb" src="${t.cover || defaultArt}">
                    <div class="track-info">
                        <div class="track-title">${t.title}</div>
                        <div class="track-artist">${t.artist}</div>
                    </div>
                </div>
            `).join('');
        }

        function selectTrack(i) {
            currentIndex = i;
            renderLibrary();
            updateDisplay();
            bridge.playTrack(library[i].path);
            updatePlayPauseUI(true);
        }

        function updatePlayPauseUI(isPlaying) {
            document.getElementById('play-icon').style.display = isPlaying ? 'none' : 'block';
            document.getElementById('pause-icon').style.display = isPlaying ? 'block' : 'none';
            const btn = document.querySelector('.play-pause-btn');
            if (isPlaying) btn.classList.add('playing');
            else btn.classList.remove('playing');
        }

        function updateDisplay() {
            const t = library[currentIndex];
            document.getElementById('main-title').textContent = t.title;
            document.getElementById('main-artist').textContent = t.artist;
            document.getElementById('main-art').src = t.cover || defaultArt;
        }

        function playNext() {
            if (currentIndex < library.length - 1) selectTrack(currentIndex + 1);
        }

        function playPrev() {
            if (currentIndex > 0) selectTrack(currentIndex - 1);
        }

        function formatTime(s) {
            const m = Math.floor(s / 60);
            const r = Math.floor(s % 60);
            return m + ':' + r.toString().padStart(2, '0');
        }

        function seek(e) {
            const rect = document.getElementById('seek-wrap').getBoundingClientRect();
            const p = (e.clientX - rect.left) / rect.width;
            bridge.setPosition(p);
        }

        // Modal Logic
        function openMetaModal() {
            if (currentIndex === -1) return;
            const t = library[currentIndex];
            document.getElementById('meta-title').value = t.title;
            document.getElementById('meta-artist').value = t.artist;
            document.getElementById('meta-album').value = t.album;
            document.getElementById('meta-year').value = t.year;
            document.getElementById('meta-genre').value = t.genre;
            document.getElementById('meta-modal').style.display = 'flex';
        }

        function closeMetaModal() {
            document.getElementById('meta-modal').style.display = 'none';
        }

        async function saveMeta() {
            const t = library[currentIndex];
            const meta = {
                title: document.getElementById('meta-title').value,
                artist: document.getElementById('meta-artist').value,
                album: document.getElementById('meta-album').value,
                year: document.getElementById('meta-year').value,
                genre: document.getElementById('meta-genre').value,
            };

            const file = document.getElementById('meta-cover-input').files[0];
            if (file) {
                const reader = new FileReader();
                meta.cover_base64 = await new Promise(resolve => {
                    reader.onload = e => resolve(e.target.result);
                    reader.readAsDataURL(file);
                });
            }

            bridge.saveMetadata(t.path, JSON.stringify(meta));
            closeMetaModal();
        }
    </script>
</body>
</html>
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern Music Player")
        self.resize(1200, 800)

        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        self.bridge = PlayerBridge(None)
        self.player_ctrl = PlayerController(self.bridge)
        self.bridge.player_ctrl = self.player_ctrl

        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.browser.page().setWebChannel(self.channel)

        self.browser.setHtml(HTML_CONTENT)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
