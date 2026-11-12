"""PMTiles（1ファイルの地図）を、区画ごとの小さなファイル（z/x/y.pbf）に分ける（GitHub Actions から実行）。
使い方: python3 scripts/pmtiles_to_dir.py 入力.pmtiles 出力フォルダ 西経度 南緯度 東経度 北緯度
- 追加の道具は使わず、PMTiles 第3版の仕様どおりに読む
- 区画のデータが gzip で縮められていれば、ほどいてから保存する（ブラウザがそのまま読めるように）
- 最後に、分けた区画が指定の範囲に入っているかを確かめる（読み方を間違えていたら失敗にする）
"""
import gzip, math, os, struct, sys

def varint(buf, pos):
    v = shift = 0
    while True:
        b = buf[pos]; pos += 1
        v |= (b & 0x7F) << shift
        if b < 0x80: return v, pos
        shift += 7

def decompress(data, kind):
    if kind in (0, 1): return data            # 0=不明, 1=なし
    if kind == 2: return gzip.decompress(data)  # 2=gzip
    raise SystemExit(f"対応していない圧縮方式です（{kind}）")

def read_dir(data):
    n, p = varint(data, 0)
    ids, runs, lens, offs = [], [], [], []
    last = 0
    for _ in range(n):
        d, p = varint(data, p); last += d; ids.append(last)
    for _ in range(n):
        v, p = varint(data, p); runs.append(v)
    for _ in range(n):
        v, p = varint(data, p); lens.append(v)
    for i in range(n):
        v, p = varint(data, p)
        offs.append(offs[i-1] + lens[i-1] if (v == 0 and i > 0) else v - 1)
    return list(zip(ids, runs, lens, offs))

def zxy(tile_id):
    """区画の番号（ヒルベルト曲線の順）→ ズーム, x, y"""
    z, acc = 0, 0
    while acc + 4 ** z <= tile_id:
        acc += 4 ** z; z += 1
    t, n, s, x, y = tile_id - acc, 2 ** z, 1, 0, 0
    while s < n:
        rx = 1 & (t // 2); ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1: x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx; y += s * ry; t //= 4; s *= 2
    return z, x, y

def tile_range(z, w, s, e, n):
    def tx(lon): return int((lon + 180) / 360 * 2 ** z)
    def ty(lat):
        r = math.radians(lat); return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z)
    return tx(w), tx(e), ty(n), ty(s)

def main(src, out, w, s, e, n):
    w, s, e, n = map(float, (w, s, e, n))
    buf = open(src, "rb").read()
    if buf[:7] != b"PMTiles" or buf[7] != 3:
        raise SystemExit("PMTiles 第3版のファイルではありません")
    (root_off, root_len, _mo, _ml, leaf_off, _ll, data_off, _dl) = struct.unpack_from("<8Q", buf, 8)
    internal, tile_comp, tile_type, minz, maxz = buf[97], buf[98], buf[99], buf[100], buf[101]
    print(f"見出し：ズーム{minz}〜{maxz}、区画の種類 {tile_type}、区画の圧縮 {tile_comp}、目次の圧縮 {internal}")

    count, bad = 0, []
    def walk(off, length):
        nonlocal count
        for tid, run, ln, of in read_dir(decompress(buf[off:off + length], internal)):
            if run == 0:                       # 下の階層の目次
                walk(leaf_off + of, ln); continue
            data = decompress(buf[data_off + of:data_off + of + ln], tile_comp)
            for k in range(run):
                z, x, y = zxy(tid + k)
                x0, x1, y0, y1 = tile_range(z, w, s, e, n)
                if not (x0 <= x <= x1 and y0 <= y <= y1): bad.append((z, x, y))
                path = os.path.join(out, str(z), str(x), f"{y}.pbf")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f: f.write(data)
                count += 1
    walk(root_off, root_len)
    print(f"区画のファイル {count} 個を {out} に保存")
    if count == 0 or len(bad) > count * 0.05:
        raise SystemExit(f"範囲の外の区画が多すぎます（{len(bad)}個、例 {bad[:5]}）。読み方が間違っている可能性があります")
    if bad: print(f"範囲の外の区画（端の分）：{len(bad)}個")

if __name__ == "__main__":
    main(*sys.argv[1:7])
