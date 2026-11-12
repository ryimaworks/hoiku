"""地図の見た目の設定・記号の画像・文字の形・地図の部品を取得して map/ に保存する（GitHub Actions から実行）。
使い方: python3 scripts/fetch_map_assets.py map
保存先:
  map/style/std.json   … 地理院の見た目の設定（記号・文字・地図データの場所を自前の場所に書き換え）
  map/sprite/          … 記号の画像
  map/glyphs/          … 文字の形（英数字・記号など。漢字・かなは端末のフォントで描くので取得しない）
  map/lib/             … MapLibre GL の部品（版を固定）
  map/取得記録.json     … いつ・どこから取得したか
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

STYLE_URL = "https://gsi-cyberjapan.github.io/optimal_bvmap/style/std.json"
LIBS = {
    "maplibre-gl.js": "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js",
    "maplibre-gl.css": "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css",
}
# 文字の形の範囲：漢字・ハングル・私用領域など（端末のフォントで描く／使わない）を除く、すべての範囲。
# 足りない範囲があると、その文字を含む区画の地図が丸ごと表示されなくなるため、多めに取る（ない範囲は飛ばす）
SKIP = [(13312, 40959), (44032, 55295), (55296, 63743)]  # 漢字（拡張A含む）、ハングル、サロゲート・私用領域
GLYPH_RANGES = [f"{a}-{a + 255}" for a in range(0, 65536, 256)
                if not any(lo <= a and a + 255 <= hi for lo, hi in SKIP)]
UA = {"User-Agent": "map-asset-fetch/1.0 (static site build)"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    print(f"保存 {path}（{len(data):,} バイト）")

def font_stacks(style):
    """text-font に出てくる書体の組をすべて集める（式の中に書かれたものも探す）"""
    stacks = set()
    def walk(v):
        if isinstance(v, list):
            # 書体名は「NotoSansJP-Regular」のように大文字・ハイフン・空白を含む（式の命令名 zoom, get などは小文字の1語）
            if v and all(isinstance(x, str) and (x != x.lower() or "-" in x or " " in x) for x in v):
                stacks.add(",".join(v))
            else:
                for x in v: walk(x)
    for l in style.get("layers", []):
        walk((l.get("layout") or {}).get("text-font"))
    return sorted(stacks)

def main(out):
    log = {"取得日時": datetime.now(timezone.utc).isoformat(), "見た目の設定": STYLE_URL, "取得したもの": [], "取得できなかったもの": []}
    style = json.loads(get(STYLE_URL))

    # 記号の画像
    sprite = style.get("sprite")
    if isinstance(sprite, list):  # 複数ある形式は最初の1つだけ使う
        sprite = sprite[0]["url"] if sprite else None
    if sprite:
        base = urllib.parse.urljoin(STYLE_URL, sprite)
        name = os.path.basename(base)
        for suf in [".json", ".png", "@2x.json", "@2x.png"]:
            try:
                save(os.path.join(out, "sprite", name + suf), get(base + suf)); log["取得したもの"].append(base + suf)
            except Exception as e:
                print(f"取得できず {base + suf}: {e}"); log["取得できなかったもの"].append(base + suf)
        style["sprite"] = "../sprite/" + name

    # 文字の形
    glyphs = style.get("glyphs")
    if glyphs:
        tmpl = urllib.parse.urljoin(STYLE_URL, glyphs).replace("%7B", "{").replace("%7D", "}")
        stacks = font_stacks(style)
        print(f"書体の組：{stacks}、範囲 {len(GLYPH_RANGES)} 個ずつ")
        for fs in stacks:
            got = 0
            for rg in GLYPH_RANGES:
                url = tmpl.replace("{fontstack}", urllib.parse.quote(fs)).replace("{range}", rg)
                try:
                    data = get(url)
                except urllib.error.HTTPError as e:
                    if e.code == 404: continue  # その範囲の文字がない（正常）
                    print(f"取得できず {url}: {e}"); log["取得できなかったもの"].append(url); continue
                path = os.path.join(out, "glyphs", fs, rg + ".pbf")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f: f.write(data)
                got += 1
            print(f"文字の形 {fs}：{got} 個保存"); log["取得したもの"].append(f"glyphs {fs} {got}個")
        style["glyphs"] = "../glyphs/{fontstack}/{range}.pbf"

    # 地図データの場所：地理院のPMTilesを、区画ごとに分けた map/tiles に向ける
    for k, src in style.get("sources", {}).items():
        where = json.dumps(src)
        if "optimal_bvmap" in where and src.get("type") == "vector":
            # 場所だけ自前の区画ファイル（map/tiles/z/x/y.pbf）に替え、ほかの設定は元のまま残す。
            # 切り出した範囲（bounds）の外の区画は取りに行かない
            new = dict(src)
            new.pop("url", None)
            new["tiles"] = ["LOCAL_TILES/{z}/{x}/{y}.pbf"]
            new["bounds"] = [139.695, 35.685, 139.795, 35.750]
            style["sources"][k] = new
            print(f"地図データの場所を自前に変更：{k}（元の設定 {where[:300]}）")
        else:
            print(f"注意：自前にしていない地図データ {k}: {where[:200]}")
            log["取得できなかったもの"].append(f"source {k}（外部のまま）")
    save(os.path.join(out, "style", "std.json"), json.dumps(style, ensure_ascii=False, indent=1).encode("utf-8"))

    # 地図の部品
    for name, url in LIBS.items():
        save(os.path.join(out, "lib", name), get(url)); log["取得したもの"].append(url)

    save(os.path.join(out, "取得記録.json"), json.dumps(log, ensure_ascii=False, indent=1).encode("utf-8"))

if __name__ == "__main__":
    main(sys.argv[1])
