"""Проверка ролика Veo: разрешение, полосы, выход за кадр, фон, петля, зум/поза.
usage: check_clip.py video.mp4 [--sheet out.jpg]  (лист из 6 кадров для просмотра)"""
import sys, cv2, numpy as np, argparse, subprocess, json
ap=argparse.ArgumentParser(); ap.add_argument("video"); ap.add_argument("--sheet"); a=ap.parse_args()
pr=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
   "stream=width,height,r_frame_rate,nb_frames,duration","-of","json",a.video]))["streams"][0]
c=cv2.VideoCapture(a.video); F=[]
while True:
    ok,f=c.read()
    if not ok: break
    F.append(f)
H,W=F[0].shape[:2]; n=len(F); issues=[]
if (W,H)!=(1920,1080): issues.append(f"разрешение {W}x{H}, нужно 1920x1080 (правило: Upscaled 1080p)")
def pet(f):
    b,g,r=[f[...,i].astype(int) for i in range(3)]
    m=((g-np.maximum(r,b))<40).astype(np.uint8)
    m=cv2.morphologyEx(m,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))
    k,l,st,_=cv2.connectedComponentsWithStats(m)
    if k<2: return m,None
    j=1+np.argmax(st[1:,4]); mm=(l==j).astype(np.uint8)
    return mm,st[j,:4]
bars=0; edge=0; boxes=[]; bgstd=[]; junk=[]
for i,f in enumerate(F):
    g=f.astype(int)
    if min(g[:,:6].mean(),g[:,-6:].mean(),g[:6].mean(),g[-6:].mean())<25: bars+=1
    m,bb=pet(f); boxes.append(bb)
    if bb is not None:
        x,y,w,h=bb
        if x<=2 or y<=2 or x+w>=W-2 or y+h>=H-2: edge+=1
    bg=(pet(f)[0]==0)
    b,gg,r=[f[...,k].astype(int) for k in range(3)]
    notgreen=((gg-np.maximum(r,b))<40)&(m==0)
    junk.append(notgreen.mean()*100)
    bgstd.append(f[bg&~notgreen].reshape(-1,3).std(0).max() if (bg&~notgreen).any() else 0)
if bars: issues.append(f"чёрные полосы на {bars} кадрах (правило: картинка ровно 16:9, без letterbox)")
if edge: issues.append(f"пет касается края кадра на {edge} кадрах (правило: целиком в кадре)")
bx=np.array([b for b in boxes if b is not None],float)
h0=bx[0,3]; hr=bx[:,3]/h0; bot=bx[:,1]+bx[:,3]
print(f"{a.video}\n  {W}x{H}, {pr.get('r_frame_rate')}, {n} кадров, {float(pr.get('duration',0)):.2f} с")
print(f"  высота пета: кадр0 {h0/H*100:.0f}% кадра, мин {hr.min():.2f}, макс {hr.max():.2f} от кадра0; низ лап сдвиг до {np.abs(bot-bot[0]).max():.0f} px")
if hr.min()<0.8: issues.append(f"пет становится ниже на {100-hr.min()*100:.0f}% (кадр {hr.argmin()}): сел/присел/лёг (правило: всегда стоит)")
if hr.max()>1.12: issues.append(f"пет выше на {hr.max()*100-100:.0f}% (кадр {hr.argmax()}): прыжок или зум")
if np.abs(bot-bot[0]).max()>40: issues.append(f"лапы отрываются/съезжают до {np.abs(bot-bot[0]).max():.0f} px (кадр {np.abs(bot-bot[0]).argmax()})")
print(f"  фон: разброс цвета до {max(bgstd):.1f}, не-зелёный мусор вне пета до {max(junk):.2f}% кадра")
if max(junk)>0.3: issues.append(f"на фоне посторонние пятна/тень до {max(junk):.1f}% кадра (кадр {int(np.argmax(junk))})")
# петля
def small(f): return cv2.resize(f,(480,270),interpolation=cv2.INTER_AREA).astype(np.float32)
s0=small(F[0]); d=[np.abs(small(f)-s0).mean() for f in F]
st=int(n*0.85); j=st+int(np.argmin(d[st:]))
print(f"  петля: разница последнего кадра с первым {d[-1]:.2f}, лучший кадр склейки {j} ({d[j]:.2f}); середина ролика до {max(d):.1f}")
if d[j]>3.0: issues.append(f"последний кадр не совпадает с первым (лучшее {d[j]:.1f} на кадре {j}): петля дёрнется")
print("  ИТОГ:", "годен" if not issues else "")
for s in issues: print("   -",s)
if a.sheet:
    idx=np.linspace(0,n-1,6).astype(int)
    t=[cv2.putText(cv2.resize(F[i],(640,360)),str(i),(10,30),0,1,(0,0,255),2) for i in idx]
    cv2.imwrite(a.sheet,np.vstack([np.hstack(t[:3]),np.hstack(t[3:])]),[cv2.IMWRITE_JPEG_QUALITY,80])
