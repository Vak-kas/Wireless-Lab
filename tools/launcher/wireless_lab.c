/*
 * Wireless Lab 의 macOS 실행 파일. 파이썬을 "이 프로그램 안에서" 돌린다(임베딩).
 *
 * 왜 필요한가
 *   macOS 는 Dock 과 메뉴 막대의 이름·아이콘을, 돌고 있는 실행 파일이 들어 있는 앱 꾸러미(.app)에서 읽는다.
 *   파이썬을 따로 띄우면 그 실행 파일은 Python.app 안에 있어서 이름이 "Python" 으로 나온다.
 *   이 실행 파일은 "Wireless Lab.app" 안에 놓이고, 파이썬 해석기를 라이브러리로 불러 tools/app.py 를 직접 돌린다.
 *   그래서 돌고 있는 프로그램이 곧 Wireless Lab 이다.
 *
 * 만드는 법: tools/make_app.py (경로들을 -D 로 넣어 clang 으로 만든다). 이 컴퓨터의 파이썬에 맞춰 만들어지므로
 *   저장소에 넣지 않는다(sessions/run/ 아래에 생긴다).
 *
 * 폴더 접근
 *   저장소가 데스크탑·문서 폴더 안에 있으면 처음 한 번 macOS 가 "Wireless Lab 이 … 폴더에 접근하려고 합니다"를 묻는다.
 *   허용하지 않으면 여기서는 아무것도 읽을 수 없다. 그때는 표시 파일(FAIL_MARK)을 남기고 알린 뒤 끝낸다:
 *   실행기(Wireless Lab.app 의 스크립트)가 그 표시를 보고 다음부터는 예전 방식(launchd + Python)으로 띄운다.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef ROOT
#error "tools/make_app.py 로 만드세요(ROOT, VENV_PYTHON, APP_PY 가 필요합니다)"
#endif

static void temp_path(char *out, size_t size, const char *name) {
    const char *tmp = getenv("TMPDIR");
    snprintf(out, size, "%s/%s", (tmp && *tmp) ? tmp : "/tmp", name);
}

static int give_up(const char *why) {
    char mark[1024];
    temp_path(mark, sizeof mark, "wirelesslab-native-failed");
    FILE *f = fopen(mark, "w");
    if (f) {
        fprintf(f, "%s\n", why);
        fclose(f);
    }
    /* 알림 창: 사용자가 무슨 일인지 알 수 있게(이 프로그램에는 터미널이 없다) */
    execl("/usr/bin/osascript", "osascript", "-e",
          "display alert \"Wireless Lab\" message \"이 프로그램이 저장소 폴더를 읽을 수 없습니다(폴더 접근이 허용되지 않았습니다). "
          "Wireless Lab 을 한 번 더 열면 예전 방식으로 켜집니다. 이름까지 Wireless Lab 으로 띄우려면 "
          "시스템 설정 > 개인정보 보호 및 보안 > 파일 및 폴더 에서 Wireless Lab 을 허용하세요.\"",
          (char *)NULL);
    return 1;
}

int main(int argc, char **argv) {
    /* Finder 에서 연 프로그램은 PATH 가 짧다: uhd·cmake 등이 있는 곳을 넣는다 */
    setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);

    char log_path[1024];
    temp_path(log_path, sizeof log_path, "nrtrail-app.log");
    if (!isatty(fileno(stdout))) {            /* 터미널에서 직접 돌릴 때는 화면에 그대로 보인다 */
        freopen(log_path, "a", stdout);
        freopen(log_path, "a", stderr);
        setvbuf(stdout, NULL, _IOLBF, 0);
    }

    if (access(APP_PY, R_OK) != 0 || chdir(ROOT) != 0) return give_up("저장소 폴더를 읽을 수 없습니다");

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    /* 실행 파일을 가상환경의 python 으로 알려 준다: 그 옆의 pyvenv.cfg 를 보고 가상환경의 패키지를 쓴다 */
    PyStatus status = PyConfig_SetBytesString(&config, &config.executable, VENV_PYTHON);
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesString(&config, &config.program_name, VENV_PYTHON);

    char **args = calloc((size_t)argc + 2, sizeof(char *));
    int n = 0;
    args[n++] = (char *)VENV_PYTHON;
    args[n++] = (char *)APP_PY;
    for (int k = 1; k < argc; k++) {
        if (strncmp(argv[k], "-psn_", 5) == 0) continue;   /* Finder 가 붙이는 인자 */
        args[n++] = argv[k];
    }
    if (!PyStatus_Exception(status)) status = PyConfig_SetBytesArgv(&config, n, args);
    if (!PyStatus_Exception(status)) status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        fprintf(stderr, "파이썬을 시작하지 못했습니다: %s\n", status.err_msg ? status.err_msg : "?");
        return give_up("파이썬을 시작하지 못했습니다");
    }
    return Py_RunMain();                      /* tools/app.py 를 __main__ 으로 돌린다. 창을 닫으면 돌아온다 */
}
