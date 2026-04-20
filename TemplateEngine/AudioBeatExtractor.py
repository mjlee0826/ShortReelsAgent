import librosa

class AudioBeatExtractor:
    """
    Adapter Pattern: 封裝 Librosa 音訊處理。
    """
    def get_beats(self, audio_path: str) -> dict:
        print(f"[Analyzer] 正在分析音樂節拍與能量點 (Beats & Onsets)...")
        y, sr = librosa.load(audio_path)
        
        # 1. 估算 BPM 與 Beat Timestamps
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # 2. 偵測能量爆發點 (Onset) - 適合轉場對齊
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)

        return {
            "bpm": round(float(tempo), 1),
            "beats": [round(float(t), 3) for t in beat_times],
            "onsets": [round(float(t), 3) for t in onset_times]
        }