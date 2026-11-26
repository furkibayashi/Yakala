# Yol haritası

Bu liste, benzer uygulamaların incelenmesinden çıkan fikirlerden oluşuyor. İncelenenler:

- **Masaüstü indiriciler:** 4K Video Downloader, JDownloader 2, Stacher, Parabolic, Open Video Downloader,
  Media Downloader, Tartube, ytDownloader, Seal (Android)
- **Web, mobil ve eklentiler:** cobalt, SnapTik / ssstik, SaveFrom, Video DownloadHelper, NewPipe,
  Instagram hikâye kaydedicileri
- **Motorlar:** yt-dlp ve gallery-dl'in arayüzlerde pek kullanılmayan özellikleri

## 1.1'de yapılanlar

| Özellik | Neden seçildi |
|---|---|
| Motorların kendini güncellemesi | Bütün rakiplerde en sık şikâyet: site değişince uygulama bozuluyor, güncelleme gecikiyor |
| Klip kesme + bölümden seçme | ytDownloader, Stacher ve Parabolic'te öne çıkan özellik |
| SponsorBlock | Tartube ve Seal kullanıcılarının sevdiği özellik |
| Bölümlere ayırma | Seal; albüm ve dersleri tek tek dosya yapma isteği |
| Ses dili seçimi | 4K Video Downloader'ın satış noktası; Open Video Downloader'da şikâyet konusu |
| Paylaşım boyutu sınırı (10/25/50 MB) | Discord/WhatsApp'a gönderme isteği; yt-dlp'nin boyut sıralaması güvenilir olmadığı için kendi seçicimizle |
| Hızlı mod | 4K "Smart Mode", Stacher hazır ayarları: sık kullananlar seçim ekranı istemiyor |
| "Daha önce indirdin" uyarısı | Tartube / Open Video Downloader'da istenen tekrar indirme engeli |
| Açıklama ve hashtag'leri .txt olarak kaydetme | gallery-dl metadata, cobalt; özellikle Instagram ve TikTok kullanıcıları |

## Sıradaki fikirler

Değer (1–5) ve zorluk analizcilerin değerlendirmesinden alındı.

| Fikir | Değer | Zorluk | Not |
|---|---|---|---|
| Kanal / profil abonelikleri: yeni videoları otomatik indir | 5 | Orta | `--download-archive` + `--break-on-existing`; 4K bunu ücretli satıyor |
| Profil arşivleyici (gönderi, reels, hikâye, öne çıkan, profil fotoğrafı) | 5 | Orta | gallery-dl `include`; Instagram için giriş gerekir |
| Tarayıcıdan "Yakala'ya gönder" (eklenti + `yakala://` bağlantısı) | 4 | Orta–Yüksek | Video DownloadHelper, Parabolic |
| Sistem tepsisinde çalışma ve arka planda pano izleme | 4 | Orta | Kopyala-unut toplu indirme |
| TikTok orijinal sesini indirme | 4 | Düşük–Orta | cobalt `tiktokFullAudio` |
| Profil fotoğrafını tam boyut indirme | 4 | Düşük | gallery-dl `include: avatar` |
| WhatsApp uyumlu H.264'e dönüştürme | 4 | Orta | Yeniden kodlama yavaş; isteğe bağlı |
| Ses yüksekliğini eşitleme | 3 | Orta | ffmpeg `loudnorm` |
| Canlı yayını baştan kaydetme | 3 | Orta | `--live-from-start` (deneysel) |
| aria2c ile çoklu bağlantı | 3 | Düşük | Parabolic'te takılma hataları görülmüş; isteğe bağlı olmalı |
| Kuyruk/geçmiş dışa ve içe aktarma | 2 | Düşük | Bilgisayar değiştirirken |

## Kaçınılacaklar

Rakiplerin kullanıcıları en çok şunlardan şikâyet ediyor:

- Reklam, sahte "indir" düğmeleri, ücretli sürüme yönlendirme, çıktıya filigran.
- Kurulum paketine eklenen istenmeyen yazılımlar (JDownloader).
- Bot doğrulaması ve giriş hatalarında yol göstermeyen mesajlar.
- Ağır ve yavaş açılan arayüz.
- Şifre ve çerezlerin düz metin olarak saklanması.
- Bitmeyen "bilgiler alınıyor" aşaması (zaman aşımı ve iptal olmalı).
