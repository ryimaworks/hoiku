#!/bin/sh
# Cloudflare Workers の「ビルドコマンド」から呼ぶ。site/ の中身を out/ に写し、
# index.html があるフォルダ（区のページ・秘密のフォルダ）ごとに地図の部品（map/）を入れる。
set -eu
rm -rf out
mkdir out
cp -R site/. out/
for d in out/*/; do
  if [ -f "${d}index.html" ]; then cp -R map "${d}map"; fi
done
echo "out/ に $(find out -type f | wc -l) 個のファイルを用意しました"
