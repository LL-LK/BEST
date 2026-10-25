# 临时检视脚本 5：把指令段写出到临时文件以便用 read 工具正确查看（只读源文件）
p = r"G:/tw/twskills/astro-best/temp/indep3/B2a__E5-D07__a3.prompt.txt"
raw = open(p, encoding="utf-8").read()
fence = "`" * 3
tail = raw.split(fence)[-1]
out = r"G:/tw/twskills/astro-best/temp/indep3/_tail_decoded.txt"
with open(out, "w", encoding="utf-8") as fh:
    fh.write(tail)
print("wrote", out, "chars", len(tail))
