# Fatura Takip

CK Boğaziçi Elektrik, İSKİ ve İGDAŞ faturalarını otomatik olarak
toplamak, arşivlemek ve web arayüzünden görüntülemek için geliştirilmiş
Docker tabanlı fatura takip sistemi.

## Özellikler

- CK Boğaziçi Elektrik fatura takibi
- İSKİ fatura takibi
- İGDAŞ fatura takibi
- Chromium üzerinden otomatik oturum yönetimi
- e-Devlet üzerinden İSKİ / İGDAŞ giriş desteği
- Fatura PDF / belge arşivi
- SQLite veritabanı
- Web dashboard
- Telegram bildirim desteği
- systemd timer ile otomatik kontroller
- Otomatik veritabanı ve belge yedekleme
- Tek komutla kurulum
- Kurulum öncesi güvenli paket kontrolü

## Gereksinimler

Desteklenen ortam:

- Linux
- Docker
- Docker Compose plugin
- systemd
- Python 3
- SQLite3
- curl

Kurulum betiği gerekli bileşenleri ayrıca kontrol eder.

## Kurulum

Projeyi sunucuya kopyaladıktan sonra proje dizinine girin:

    cd fatura-takip

Önce paketi kontrol edin:

    ./install.sh --check

Kontrol başarılıysa kurulumu başlatın:

    sudo ./install.sh

Varsayılan kurulum dizini:

    /opt/fatura-takip

Farklı bir dizine kurmak için:

    sudo FATURA_TAKIP_DIR=/opt/fatura-takip-test ./install.sh

## Yapılandırma

Örnek yapılandırmayı kopyalayın:

    cp .env.example .env

Ardından `.env` dosyasını kendi bilgilerinizle düzenleyin.

Desteklenen temel değişkenler:

    CK_ACCOUNT_ID=
    CK_LOGIN_ID=
    CK_LOGIN_PASSWORD=
    CK_BILL_COUNT=12

    EDEVLET_TCKN=
    EDEVLET_PASSWORD=

    TELEGRAM_BOT_TOKEN=
    TELEGRAM_CHAT_ID=

`.env` dosyası kişisel bilgiler ve erişim bilgileri içerebilir.
Bu dosyayı paylaşmayın veya Git deposuna eklemeyin.

## Web Arayüzleri

Dashboard:

    http://SUNUCU_IP:8180

Chromium:

    http://SUNUCU_IP:3100

## Manuel Fatura Kontrolü

CK Boğaziçi:

    systemctl start fatura-ck.service

İSKİ:

    systemctl start fatura-iski.service

İGDAŞ:

    systemctl start fatura-igdas.service

## Otomatik Kontroller

Timer'ları etkinleştirmek için:

    systemctl enable --now fatura-ck.timer
    systemctl enable --now fatura-iski.timer
    systemctl enable --now fatura-igdas.timer

Durumlarını görmek için:

    systemctl list-timers 'fatura-*'

Kurulum sırasında provider timer'ları varsayılan olarak etkinleştirilmez.
Kullanıcı istediği zaman yukarıdaki komutlarla etkinleştirebilir.

## Yedekleme

Günlük yedekleme timer'ı:

    fatura-backup.timer

Durum:

    systemctl status fatura-backup.timer

## Paket Kontrolü

Kurulum yapmadan paketin bütünlüğünü ve temel yapılandırmasını
kontrol etmek için:

    ./install.sh --check

Bu kontrol:

- gerekli dosyaları
- bağımlılıkları
- shell syntax'larını
- Python syntax'larını
- SQLite şemasını
- systemd template'lerini
- Docker Compose yapılandırmasını
- eski image / override referanslarını

kontrol eder.

`--check` modu container başlatmaz ve sistemi değiştirmez.

## Veri Dizinleri

Runtime verileri:

    data/

Fatura belgeleri:

    pdfs/

Chromium oturum bilgileri:

    auth/chromium/

Bu dizinlerin runtime içerikleri `.gitignore` tarafından hariç tutulur.

## Güvenlik

Aşağıdaki dosya ve verileri paylaşmayın:

- `.env`
- SQLite veritabanları
- fatura PDF / görselleri
- Chromium profil ve oturum dosyaları
- erişim token'ları
- kullanıcı adı / parola bilgileri

Public paket yalnızca örnek `.env.example` dosyasını içerir.

## Docker Servisleri

Sistem üç temel Docker servisinden oluşur:

- `browser`
- `collector`
- `dashboard`

Collector image'i CK Boğaziçi, İSKİ ve İGDAŞ collector kodlarını birlikte içerir.

## Veritabanı

SQLite veritabanında temel olarak şu tablolar bulunur:

- `invoices`
- `notifications`
- `system_alerts`

Yeni kurulumda şema `database/init.sql` üzerinden oluşturulur.

## Not

Elektrik, su, doğalgaz sağlayıcılarının web servisleri ve giriş
akışları zaman içerisinde değişebilir. Böyle bir değişiklik collector
kodlarının güncellenmesini gerektirebilir.

Bu proje resmi CK Enerji, İSKİ, İGDAŞ veya e-Devlet uygulaması değildir.
