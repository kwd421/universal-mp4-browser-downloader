# Universal MP4 Browser Downloader

URL을 붙여넣으면 yt-dlp로 영상 후보를 분석하고, 원하는 품질을 골라 MP4/WEBM/WAV로 저장하는 간단한 GUI 앱입니다.

## 기능

- URL 분석 후 같은 영상은 한 줄로 묶고 품질은 드롭다운으로 선택합니다.
- 후보는 썸네일, 제목, 길이, 확장자, 품질, 예상 크기를 보여줍니다.
- Chrome, Edge, Firefox 쿠키 읽기 옵션을 지원합니다.
- 일반 추출이 TLS/브라우저 지문 문제로 실패하면 설치된 Chrome/Edge/Chromium의 headless DOM 분석 fallback을 사용합니다.
- 다운로드 파일명은 UI에 보이는 영상 제목을 기준으로 만들고, `pornhub.com` 같은 trailing 도메인 꼬리는 제거합니다.
- DRM, CAPTCHA, 유료/비공개 권한 우회는 하지 않습니다.

## Windows 빌드

```powershell
cd C:\Users\Fleurdelys\Downloads\nothing
powershell -ExecutionPolicy Bypass -File build-helper\build_windows.ps1
```

빌드 결과:

- `UniversalMP4BrowserDownloader.exe`
- `dist\UniversalMP4BrowserDownloader.exe`

## macOS 빌드

PyInstaller는 Windows에서 macOS 앱을 cross-build하지 못합니다. Mac에서 이 저장소를 클론한 뒤 빌드해야 합니다.

```bash
cd /path/to/nothing
bash build-helper/build_macos.sh
```

빌드 결과는 환경에 따라 다음 중 하나입니다.

- `dist/UniversalMP4BrowserDownloader`
- `dist/UniversalMP4BrowserDownloader.app`

macOS에서 PornHub류 TLS/브라우저 지문 fallback까지 쓰려면 Chrome, Edge, 또는 Chromium 중 하나가 설치되어 있어야 합니다. 직접 경로를 지정하려면 `UMP4_BROWSER_PATH` 환경변수를 사용하세요.

## 개발 검증

```bash
python -m unittest discover -s test -p "test_*.py" -v
```

## 배포 참고

Windows SmartScreen과 macOS Gatekeeper 경고는 코드 서명과 notarization 없이는 완전히 제거할 수 없습니다. 공개 배포 단계에서는 플랫폼별 서명 작업을 별도로 해야 합니다.
