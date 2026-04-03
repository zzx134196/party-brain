#!/bin/bash
cd "$(dirname "$0")"
git add -A
git commit -m "${1:-更新代码}"
git -c credential.helper='!f() { echo "username=zzx134196"; echo "password=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"; }; f' push origin main
