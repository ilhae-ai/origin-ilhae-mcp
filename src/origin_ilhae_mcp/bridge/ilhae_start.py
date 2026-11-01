# -*- coding: utf-8 -*-
"""Origin 스크립트 창에서 실행하는 브리지 시작 스크립트.

    run -pyf "<설치폴더>\\ilhae_start.py"      // 시작
    run -py "import ilhae_bridge; ilhae_bridge.stop()"   // 중지

install 명령이 이 파일과 ilhae_*.py 를 같은 폴더에 복사한다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ilhae_bridge  # noqa: E402

port = ilhae_bridge.start()
print(u"[origin-ilhae] 브리지 시작: 127.0.0.1:%d (토큰: %s)" % (port, ilhae_bridge.token_path()))
