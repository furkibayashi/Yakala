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

## 1.2'de yapılanlar

| Özellik | Neden seçildi |
|---|---|
| Takip (YouTube kanalı, oynatma listesi, TikTok profili) | İncelenen masaüstü uygulamalarının çoğunda var; 4K bunu ücretli satıyor |

X ve Instagram profillerinin takibi giriş gerektirdiği için sonraki sürümlere kaldı.

## 1.3'te yapılanlar

İki analizci çalıştı: biri kullanım senaryolarından yeni özellik fikirleri üretti, diğeri kodu satır satır inceleyip
hata ve sağlamlık sorunları buldu. Kullanıcı isteğiyle telefondan erişim de eklendi.

| Özellik / düzeltme | Kaynak |
|---|---|
| Telefondan erişim (QR, oynatma, telefona indirme, telefondan bağlantı gönderme) | Kullanıcı isteği |
| Dosyayı panoya kopyalama (CF_HDROP) | Ürün analizcisi #1 |
| Kalıcı kuyruk | Ürün #2, sağlamlık analizcisi |
| Numaralı oynatma listeleri | Ürün #4 |
| Uyku engelleme, disk alanı kontrolü, tek örnek kilidi, hata günlüğü | Sağlamlık analizcisi |
| Oynatma listesinde duraklat/iptalin durmaması (yüksek) | Sağlamlık analizcisi |
| Galeride devam edince öğelerin atlanması (yüksek) | Sağlamlık analizcisi |
| Yoklama döngülerinin çoğalması, kilitli kalan düğmeler, sınırsız kanal analizi, güncelleyicinin kullanımdaki motoru silmesi, uzantı denetimi, proxy'nin yok sayılması, çerçeveleme koruması ve diğerleri | Sağlamlık analizcisi |

## Sıradaki fikirler

Değer (1–5) ve zorluk analizcilerin değerlendirmesinden alındı.

| Fikir | Değer | Zorluk | Not |
|---|---|---|---|
| Profil arşivleyici (gönderi, reels, hikâye, öne çıkan, profil fotoğrafı) | 5 | Orta | gallery-dl `include`; Instagram için giriş gerekir |
| Tarayıcıdan "Yakala'ya gönder" (eklenti + `yakala://` bağlantısı) | 4 | Orta–Yüksek | Video DownloadHelper, Parabolic |
| Sistem tepsisinde çalışma ve arka planda pano izleme | 4 | Orta | Kopyala-unut toplu indirme |
| TikTok orijinal sesini indirme | 4 | Düşük–Orta | cobalt `tiktokFullAudio` |
| Profil fotoğrafını tam boyut indirme | 4 | Düşük | gallery-dl `include: avatar` |
| WhatsApp uyumlu H.264'e dönüştürme | 4 | Orta | Yeniden kodlama yavaş; isteğe bağlı |
| Ses yüksekliğini eşitleme | 3 | Orta | ffmpeg `loudnorm` |
| Canlı yayını baştan kaydetme | 3 | Orta | `--live-from-start` (deneysel) |
| İsimle arama ("tarkan şımarık" yazıp seç) | 4 | Orta | `ytsearch10:`; liste seçme ekranı kullanılabilir |
| Altyazıyı .srt ve düz metin döküm olarak kaydetme | 4 | Düşük | Öğrenciler için |
| Müzik etiketleri (sanatçı/başlık ayırma) ve kare kapak | 4 | Düşük | `--parse-metadata`, kırpma |
| Görev çubuğunda ilerleme ve bitince yanıp sönme | 3 | Orta | ITaskbarList3 |
| "Bitince bilgisayarı kapat" | 3 | Düşük | İptal edilebilir geri sayımla |
| Analizi iptal etme ve zaman aşımı | 5 | Orta | Sağlamlık analizcisinin önerisi |
| 429'da bekleyip yeniden deneme | 4 | Orta | Sağlamlık analizcisinin önerisi |
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
