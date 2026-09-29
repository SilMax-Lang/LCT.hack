"""Подгонка --head и --eyes по первому кадру ролика (как для среднего кота).
usage: fit_head_eyes.py video.mp4 crop_x,crop_y,side "eyes_base_px" out_prefix [--ref-video v --ref-crop ... --ref-head ...]
"""
import sys, cv2, numpy as np, argparse
ap=argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("crop"); ap.add_argument("eyes"); ap.add_argument("out")
ap.add_argument("--ref-video"); ap.add_argument("--ref-crop"); ap.add_argument("--ref-head"); ap.add_argument("--ref-eyes")
a=ap.parse_args()
def frame0(p):
    c=cv2.VideoCapture(p); ok,f=c.read(); return f
def mask(f):
    b,g,r=[f[...,i].astype(int) for i in range(3)]
    return ((g-np.maximum(r,b))<40).astype(np.uint8)
def base2vid(s):
    out=[]
    for e in s.split(";"):
        v=list(map(float,e.split(",")));pts=np.array(v).reshape(-1,2)
        pts[:,0]=(pts[:,0]-42)*1920/2731; pts[:,1]=pts[:,1]*1080/1536
        out.append(pts)
    return out
def fit_eye(f,pts):
    H,W=f.shape[:2]; poly=np.zeros((H,W),np.uint8); cv2.fillPoly(poly,[pts.astype(np.int32)],1)
    k=lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(r,r))
    near=cv2.dilate(poly,k(81)); ring=cv2.dilate(poly,k(161))-cv2.dilate(poly,k(111))
    hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV); V=hsv[...,2].astype(int); S=hsv[...,1].astype(int)
    fs=np.median(S[ring>0])
    eye=(((V>170)&(S<50))|((S>fs+50)&(V>60))|(V<40))&(near>0)
    eye=cv2.morphologyEx(eye.astype(np.uint8),cv2.MORPH_CLOSE,k(7))
    n,l,st,_=cv2.connectedComponentsWithStats(eye); keep=[j for j in range(1,n) if st[j,4]>300 and (poly[l==j]>0).any()]; eye=np.isin(l,keep).astype(np.uint8)
    hull=cv2.convexHull(cv2.findNonZero(eye)); hm=np.zeros_like(eye); cv2.fillPoly(hm,[hull],1)
    hm=hm&near; hm=cv2.erode(hm,k(15))
    cs,_=cv2.findContours(hm,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE); c=max(cs,key=cv2.contourArea)
    c=cv2.approxPolyDP(c,1.5,True)[:,0,:].astype(float)
    return c
def headbox(f,eyes):
    m=mask(f); cx=np.mean([e[:,0].mean() for e in eyes]); ey=np.mean([e[:,1].mean() for e in eyes])
    row=np.where(m[int(ey)]>0)[0]; row=row[(row>cx-600)&(row<cx+600)]
    cols=m[:, int(cx-300):int(cx+300)]; top=np.where(cols.any(1))[0][0]
    return cx, ey, row.max()-row.min(), top
def norm(pts,crop):
    x,y,s=crop; return [((px-x)/s,(py-y)/s) for px,py in pts]
crop=list(map(float,a.crop.split(",")))
f=frame0(a.video); eyes=base2vid(a.eyes); cont=[fit_eye(f,e) for e in eyes]
cx,ey,cw,top=headbox(f,eyes)
if a.ref_video:  # связь бокса головы с маской у эталона (средний)
    rf=frame0(a.ref_video); rc=list(map(float,a.ref_crop.split(",")))
    re=[np.array(list(map(float,e.split(",")))).reshape(-1,2)*rc[2]+rc[:2] for e in a.ref_eyes.split(";")]
    rcx,rey,rcw,rtop=headbox(rf,re); hx,hy,hw,hh=[float(v) for v in a.ref_head.split(",")]
    hx,hy,hw,hh=hx*rc[2]+rc[0],hy*rc[2]+rc[1],hw*rc[2],hh*rc[2]
    kw=hw/rcw; kh=(hh)/(rey-rtop); kt=(hy-rtop)/(rey-rtop); kx=(hx+hw/2-rcx)/rcw
    print("ref ratios",round(kw,3),round(kh,3),round(kt,3),round(kx,3))
    w=kw*cw; h=kh*(ey-top); y=top+kt*(ey-top); x=cx+kx*cw-w/2
else: raise SystemExit("need ref")
head=[(x-crop[0])/crop[2],(y-crop[1])/crop[2],w/crop[2],h/crop[2]]
hs=",".join(f"{v:.4f}" for v in head)
es=";".join(",".join(f"{px:.4f},{py:.4f}" for px,py in norm(c,crop)) for c in cont)
open(a.out+"head_large.txt","w").write(hs+"\n"); open(a.out+"eyes_large.txt","w").write(es+"\n")
print("head",hs); print("eye pts",[len(c) for c in cont])
# картинка проверки
x0,y0,s=[int(v) for v in crop]; big=cv2.copyMakeBorder(f,200,200,200,200,cv2.BORDER_CONSTANT)
cv2.rectangle(big,(int(x)+200,int(y)+200),(int(x+w)+200,int(y+h)+200),(0,0,255),2)
for c in cont: cv2.polylines(big,[(c+200).astype(np.int32)],True,(255,0,255),1)
X=int(x)+200; Y=int(y)+200
cv2.imwrite(a.out+"_large_check.jpg",big[max(0,Y-20):Y+int(h)+20, X-20:X+int(w)+20])
ey0=int(min(c[:,1].min() for c in cont))+200-30; ey1=int(max(c[:,1].max() for c in cont))+200+30
ex0=int(min(c[:,0].min() for c in cont))+200-30; ex1=int(max(c[:,0].max() for c in cont))+200+30
z=cv2.resize(big[ey0:ey1,ex0:ex1],None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
cv2.imwrite(a.out+"_large_eyes_zoom.jpg",z)
