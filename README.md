# BizTeam WorkRequestSplitter

작업요청서가 포함된 PDF를 자동으로 감지해서 접수번호 기준으로 분리 저장하는 Windows용 프로그램입니다.

이 프로그램은 PDF 상단의 `작업요청서` 문구와 접수번호(`N000-00-00000` 형식)를 OCR로 읽어서 문서 시작 페이지를 찾고, 각 문서를 개별 PDF로 저장합니다.

## 주요 기능

- 감시 폴더에 새 PDF가 생기면 자동 처리
- 작업요청서 페이지를 기준으로 PDF 분리
- 접수번호를 파일명으로 저장
- 분리된 파일은 `split_output` 폴더에 저장
- 처리 완료된 원본 PDF는 `split_output/_inbox_done` 폴더로 이동
- 로그를 화면과 `logs` 폴더에 기록

## 동작 방식 요약

프로그램은 실행 파일이 있는 폴더의 최상위 PDF만 감시합니다.

- 작업요청서 시작 페이지를 OCR로 검출
- 각 작업요청서 페이지를 새 문서의 시작으로 판단
- 작업요청서 첫 페이지는 결과 PDF에서 제외
- 본문 페이지만 별도 PDF로 저장
- 저장 파일명은 접수번호 기준으로 생성

예시:

- 원본 PDF 안에 `N2322603706` 작업요청서가 있으면
- 결과 파일명은 `N2322603706.pdf`

## 설치해야 하는 프로그램

이 프로그램은 단독 실행형이 아닙니다. 아래 프로그램이 별도로 설치되어 있어야 합니다.

### 1. Tesseract OCR

OCR 인식용입니다.

- 기본 경로 예시: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### 2. Poppler for Windows

PDF를 이미지로 변환할 때 필요합니다.

- 기본 경로 예시: `C:\poppler\Library\bin`

## 설정 파일

설정 파일은 아래 우선순위로 읽습니다.

1. 실행 폴더의 `config/config.ini`
2. 실행 폴더의 `config.ini`

예시:

```ini
[PATHS]
poppler_path = C:\poppler\Library\bin
tesseract_exe = C:\Program Files\Tesseract-OCR\tesseract.exe

[OCR]
dpi = 500
batch_size = 10

[WATCHER]
scan_interval_sec = 1.0
stable_check_sec = 0.7
stable_retry = 3
```

## 실행 방법

### 소스 실행

Python 환경에서 `src/main.py`를 실행합니다.

### exe 실행

배포본은 폴더째 유지해야 합니다.

- exe만 따로 꺼내서 실행하면 안 됩니다
- `_internal` 폴더가 exe 옆에 같이 있어야 합니다

권장 실행 파일 예시:

- `dist/BizTeam_WorkRequestSplitter_portable/BizTeam_WorkRequestSplitter_portable.exe`

## 사용 방법

1. 프로그램을 실행합니다.
2. 실행 파일이 있는 폴더에 PDF를 넣습니다.
3. 프로그램이 자동으로 PDF를 감지하고 처리합니다.
4. 분리된 파일은 `split_output` 폴더에 저장됩니다.
5. 원본은 `split_output/_inbox_done`으로 이동됩니다.

## 실행 후 주의 사항

### 1. PDF는 실행 폴더 최상위에 넣어야 합니다

현재 버전은 하위 폴더를 자동 스캔하지 않습니다.

### 2. 작업요청서 첫 페이지는 결과 PDF에서 제외됩니다

이 프로그램은 작업요청서 표지 페이지를 제외하고 본문만 저장하도록 동작합니다.

### 3. 작업요청서가 1장만 있으면 결과 파일이 저장되지 않을 수 있습니다

작업요청서 표지 뒤에 본문 페이지가 없으면 저장할 내용이 없다고 판단하고 스킵합니다.

### 4. OCR 품질에 따라 분리 결과가 달라질 수 있습니다

다음 경우 인식률이 떨어질 수 있습니다.

- 스캔 품질이 낮은 PDF
- 글자가 흐리거나 기울어진 PDF
- 상단 접수번호가 잘 보이지 않는 PDF

### 5. Tesseract / Poppler 경로가 맞아야 합니다

설치 경로가 다르면 `config.ini`에서 경로를 수정해야 합니다.

### 6. exe는 폴더째 배포해야 합니다

`_internal` 폴더를 삭제하거나 exe만 이동하면 실행 오류가 발생할 수 있습니다.

## 개발 메모

- 메인 코드: `src/main.py`
- 빌드 스펙: `BizTeam_WorkRequestSplitter.spec`
- 설정 파일은 Git에서 제외됨

