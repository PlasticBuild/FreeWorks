# SPDX-License-Identifier: LGPL-2.1-or-later
"""File > Publish to 3D Viewer: the eDrawings way of sharing a model, as one HTML file.

The part or assembly is written, with its components, colours, edges and exploded views, into
a single .html file that opens in any web browser with nothing to install and no internet:
rotate (left drag), pan (right or middle drag), zoom (wheel), Zoom to Fit, the standard views,
Shaded / Shaded With Edges, the components list (tick to show or hide, click to pick), the
exploded views (Explode / Collapse), and Measure (click two points for the distance).
"""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import base64
import html
import json
import os
import struct

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

GREY = (0.7, 0.7, 0.75)


def _assembly(doc):
    try:
        from . import asmcore as ac
        return ac.assembly_of(doc)
    except Exception:
        return None


def _colour(obj):
    for o in (obj, getattr(obj, "LinkedObject", None)):
        v = getattr(o, "ViewObject", None) if o is not None else None
        if v is None:
            continue
        try:
            app = v.ShapeAppearance
            if app:
                return tuple(app[0].DiffuseColor[:3])
        except Exception as _fw_err:
            _fw_log("publishview.py:53", _fw_err)
        try:
            return tuple(v.ShapeColor[:3])
        except Exception as _fw_err:
            _fw_log("publishview.py:57", _fw_err)
    return GREY


def _b64(fmt, values):
    return base64.b64encode(struct.pack("<%d%s" % (len(values), fmt), *values)).decode("ascii")


def _mesh(shape, tol):
    pts, tris = shape.tessellate(tol)
    pos = [c for p in pts for c in (p.x, p.y, p.z)]
    idx = [i for t in tris for i in t]
    lines = []
    for e in shape.Edges:
        try:
            ps = e.discretize(Deflection=tol)
        except Exception:
            continue
        for a, b in zip(ps, ps[1:]):
            lines += [a.x, a.y, a.z, b.x, b.y, b.z]
    return pos, idx, lines


def _matrix(pl):
    m = pl.toMatrix()
    return [m.A11, m.A21, m.A31, m.A41, m.A12, m.A22, m.A32, m.A42,
            m.A13, m.A23, m.A33, m.A43, m.A14, m.A24, m.A34, m.A44]     # column-major, as WebGL


def items(doc):
    """[(name, object, global shape)] of what the viewer shows."""
    asm = _assembly(doc)
    out = []
    if asm is not None:
        from . import asmcore as ac
        for c in ac.components(asm):
            s = getattr(c, "Shape", None)
            if s is None or s.isNull() or not s.Faces or not c.Visibility:
                continue
            try:
                from . import asmcomp
                if asmcomp.is_suppressed(c):
                    continue
            except Exception as _fw_err:
                _fw_log("publishview.py:101", _fw_err)
            out.append((c.Label, c, s))
        return out
    for o in doc.Objects:
        s = getattr(o, "Shape", None)
        if s is None or s.isNull() or not s.Solids or not getattr(o, "Visibility", False):
            continue
        if o.TypeId in ("Part::DatumPlane", "PartDesign::Plane"):
            continue
        out.append((o.Label, o, s))
    return _outermost(out)


def _outermost(rows):
    """fh244: a part's Body and its tip feature are both shown and both solid: the viewer drew the solid twice.
    A row inside another row (its Body, its Part container) is left out."""
    names = {o.Name for _n, o, _s in rows}
    out = []
    for row in rows:
        up, inside = row[1], False
        for _guard in range(32):
            try:
                up = up.getParentGeoFeatureGroup()
            except Exception:
                up = None
            if up is None:
                break
            if up.Name in names:
                inside = True
                break
        if not inside:
            out.append(row)
    return out


def exploded_states(doc, rows):
    """[(view name, [matrix per row])]: each exploded view's moves of the rows, as matrices
    from where they are now. The assembly is put back as it was."""
    asm = _assembly(doc)
    if asm is None:
        return []
    from . import asmexplode as ax
    out = []
    names = [o.Name for _n, o, _s in rows]
    for view in ax.views(asm):
        was = ax.is_exploded(view)
        base = {n: App.Placement(doc.getObject(n).Placement) for n in names}
        try:
            if was:
                ax.collapse(asm, view)
                base = {n: App.Placement(doc.getObject(n).Placement) for n in names}
            ax.explode(asm, view)
            mats = [_matrix(doc.getObject(n).Placement.multiply(base[n].inverse())) for n in names]
            out.append((view.Label, mats))
        finally:
            ax.collapse(asm, view)
            if was:
                ax.explode(asm, view)
    return out


def model(doc):
    rows = items(doc)
    if not rows:
        return None
    bb = None
    for _n, _o, s in rows:
        if bb is None:
            bb = App.BoundBox(s.BoundBox)
        else:
            bb.add(s.BoundBox)
    tol = max(0.01, bb.DiagonalLength * 0.002)
    parts = []
    for name, obj, shape in rows:
        pos, idx, lines = _mesh(shape, tol)
        parts.append({"name": name, "color": list(_colour(obj)), "pos": _b64("f", pos), "idx": _b64("I", idx),
                      "lines": _b64("f", lines), "n": len(idx) // 3})
    return {"title": doc.Label, "parts": parts, "views": [{"name": n, "mats": m} for n, m in exploded_states(doc, rows)],
            "box": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]}


def page(data):
    return TEMPLATE.replace("__TITLE__", html.escape(data["title"])).replace("__DATA__", json.dumps(data))


def publish(doc, path):
    data = model(doc)
    if data is None:
        return None
    with open(path, "w", encoding="utf-8") as f:
        f.write(page(data))
    return path


def start(doc=None, path=None, opener=None):
    """Save As (.html) next to the document, then open it as eDrawings opens its file."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if not path:
        base = os.path.splitext(doc.FileName)[0] if doc.FileName else os.path.join(os.path.expanduser("~"), doc.Label)
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Publish to 3D Viewer", base + ".html",
                                                         "3D Viewer page (*.html)")
        if not path:
            return None
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        out = publish(doc, path)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    if out:
        (opener or QtGui.QDesktopServices.openUrl)(QtCore.QUrl.fromLocalFile(out))
    return out


TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#dfe3ea;--bar:#f4f5f7;--ink:#1d2433;--line:#c4c9d2;--hi:#2b7ea8}
@media (prefers-color-scheme:dark){:root{--bg:#2a2d33;--bar:#1f2126;--ink:#e6e8ec;--line:#3a3e46;--hi:#5fb0db}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:13px system-ui,sans-serif;overflow:hidden}
#bar{position:absolute;left:0;right:0;top:0;display:flex;flex-wrap:wrap;gap:4px;padding:6px;background:var(--bar);border-bottom:1px solid var(--line);z-index:2}
#bar button,#bar select{font:inherit;color:inherit;background:transparent;border:1px solid var(--line);border-radius:4px;padding:3px 8px;cursor:pointer}
#bar button.on{border-color:var(--hi);color:var(--hi)}
#side{position:absolute;left:0;top:40px;bottom:0;width:200px;overflow:auto;background:var(--bar);border-right:1px solid var(--line);padding:6px;box-sizing:border-box}
#side label{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:2px 0;cursor:pointer}
#side label.pick{color:var(--hi);font-weight:600}
canvas{position:absolute;left:200px;top:40px;right:0;bottom:0;width:calc(100% - 200px);height:calc(100% - 40px)}
#info{position:absolute;right:10px;bottom:10px;background:var(--bar);border:1px solid var(--line);border-radius:4px;padding:4px 8px;display:none}
@media (max-width:600px){#side{display:none}canvas{left:0;width:100%}}
</style></head><body>
<div id="bar"><b style="padding:3px 6px">__TITLE__</b>
<button id="fit" title="Zoom to Fit">Zoom to Fit</button>
<select id="views" title="Standard views"><option value="iso">Isometric</option><option value="front">Front</option><option value="back">Back</option><option value="top">Top</option><option value="bottom">Bottom</option><option value="left">Left</option><option value="right">Right</option></select>
<button id="edges" class="on" title="Shaded With Edges">Edges</button>
<select id="explode" title="Exploded views"></select>
<button id="measure" title="Measure: click two points">Measure</button>
</div>
<div id="side"></div><canvas id="c"></canvas><div id="info"></div>
<script>
const D=__DATA__;
const cv=document.getElementById('c'),gl=cv.getContext('webgl',{antialias:true,preserveDrawingBuffer:true});
gl.getExtension('OES_element_index_uint');
function b64(s,T){const b=atob(s),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);return new T(u.buffer)}
function sh(t,s){const x=gl.createShader(t);gl.shaderSource(x,s);gl.compileShader(x);return x}
function prog(v,f){const p=gl.createProgram();gl.attachShader(p,sh(gl.VERTEX_SHADER,v));gl.attachShader(p,sh(gl.FRAGMENT_SHADER,f));gl.linkProgram(p);return p}
const P=prog('attribute vec3 p,n;uniform mat4 M,V;uniform mat3 R;varying vec3 vn;void main(){vn=R*mat3(M[0].xyz,M[1].xyz,M[2].xyz)*n;gl_Position=V*M*vec4(p,1.);}',
 'precision mediump float;varying vec3 vn;uniform vec3 C;uniform float H;void main(){vec3 n=normalize(vn);float d=abs(n.z)*.75+.25;vec3 c=mix(C,vec3(.17,.49,.66),H);gl_FragColor=vec4(c*d+vec3(.08)*pow(abs(n.z),24.),1.);}');
const L=prog('attribute vec3 p;uniform mat4 M,V;void main(){gl_Position=V*M*vec4(p,1.);gl_Position.z-=.0005*gl_Position.w;}','precision mediump float;uniform vec3 C;void main(){gl_FragColor=vec4(C,1.);}');
const I4=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const parts=D.parts.map((q,k)=>{const pos=b64(q.pos,Float32Array),idx=b64(q.idx,Uint32Array),ln=b64(q.lines,Float32Array);
 const tp=new Float32Array(idx.length*3),tn=new Float32Array(idx.length*3);
 for(let t=0;t<idx.length;t+=3){const a=idx[t]*3,b=idx[t+1]*3,c=idx[t+2]*3;
  const ux=pos[b]-pos[a],uy=pos[b+1]-pos[a+1],uz=pos[b+2]-pos[a+2],vx=pos[c]-pos[a],vy=pos[c+1]-pos[a+1],vz=pos[c+2]-pos[a+2];
  let nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;const l=Math.hypot(nx,ny,nz)||1;nx/=l;ny/=l;nz/=l;
  for(let j=0;j<3;j++){const s=idx[t+j]*3;tp.set([pos[s],pos[s+1],pos[s+2]],(t+j)*3);tn.set([nx,ny,nz],(t+j)*3)}}
 const bp=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bp);gl.bufferData(gl.ARRAY_BUFFER,tp,gl.STATIC_DRAW);
 const bn=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bn);gl.bufferData(gl.ARRAY_BUFFER,tn,gl.STATIC_DRAW);
 const bl=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bl);gl.bufferData(gl.ARRAY_BUFFER,ln,gl.STATIC_DRAW);
 const bb=[1e30,1e30,1e30,-1e30,-1e30,-1e30];for(let i=0;i<pos.length;i+=3)for(let j=0;j<3;j++){bb[j]=Math.min(bb[j],pos[i+j]);bb[j+3]=Math.max(bb[j+3],pos[i+j])}
 return {name:q.name,color:q.color,tp,bp,bn,bl,bb,nv:idx.length,nl:ln.length/3,show:true,M:I4.slice()}});
// camera: rotation R (rows = screen x,y,z in model), target, half height
const B=D.box,ctr=[(B[0]+B[3])/2,(B[1]+B[4])/2,(B[2]+B[5])/2];let rad=Math.max(1e-6,Math.hypot(B[3]-B[0],B[4]-B[1],B[5]-B[2])/2);
let R,tg=ctr.slice(),hh=rad*1.1,edges=true,pick=-1,measuring=false,mpts=[];
function norm(v){const l=Math.hypot(...v)||1;return v.map(x=>x/l)}
function cross(a,b){return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]}
function look(dir,up){const z=norm(dir.map(x=>-x)),x=norm(cross(up,z)),y=cross(z,x);R=[x,y,z]}
const VIEWS={iso:[[-1,-1,-1],[0,0,1]],front:[[0,1,0],[0,0,1]],back:[[0,-1,0],[0,0,1]],top:[[0,0,-1],[0,1,0]],bottom:[[0,0,1],[0,-1,0]],left:[[1,0,0],[0,0,1]],right:[[-1,0,0],[0,0,1]]};
function setView(k){look(...VIEWS[k]);fit()}
function fit(){let lo=[1e30,1e30,1e30],hi=[-1e30,-1e30,-1e30];
 parts.forEach(q=>{if(!q.show)return;const b=q.bb;for(let c=0;c<8;c++){const w=xf(q.M,b[c&1?3:0],b[c&2?4:1],b[c&4?5:2]);for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],w[i]);hi[i]=Math.max(hi[i],w[i])}}});
 if(lo[0]>hi[0]){tg=ctr.slice();hh=rad*1.1}else{tg=[0,1,2].map(i=>(lo[i]+hi[i])/2);const r=Math.max(1e-6,Math.hypot(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2])/2);rad=Math.max(rad,r);hh=r*1.1}draw()}
function viewMat(){const w=cv.clientWidth||1,h=cv.clientHeight||1,a=w/h,sx=1/(hh*a),sy=1/hh,sz=-1/(rad*4);
 const r=R,t=tg;const m=[];for(let c=0;c<3;c++){m.push(r[0][c]*sx,r[1][c]*sy,r[2][c]*sz,0)}
 const d=[0,1,2].map(i=>-(r[i][0]*t[0]+r[i][1]*t[1]+r[i][2]*t[2]));m.push(d[0]*sx,d[1]*sy,d[2]*sz,1);return m}
let queued=false;function draw(){if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;render()})}}
function render(){const dpr=window.devicePixelRatio||1,w=cv.clientWidth*dpr|0,h=cv.clientHeight*dpr|0;if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h}
 gl.viewport(0,0,w,h);const bg=getComputedStyle(document.body).backgroundColor.match(/\d+/g).map(x=>x/255);gl.clearColor(bg[0],bg[1],bg[2],1);
 gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);const V=viewMat();
 const Rm=[R[0][0],R[1][0],R[2][0],R[0][1],R[1][1],R[2][1],R[0][2],R[1][2],R[2][2]];
 gl.useProgram(P);const pa=gl.getAttribLocation(P,'p'),na=gl.getAttribLocation(P,'n');
 gl.uniformMatrix4fv(gl.getUniformLocation(P,'V'),false,V);gl.uniformMatrix3fv(gl.getUniformLocation(P,'R'),false,Rm);
 parts.forEach((q,k)=>{if(!q.show)return;gl.uniformMatrix4fv(gl.getUniformLocation(P,'M'),false,q.M);gl.uniform3fv(gl.getUniformLocation(P,'C'),q.color);
  gl.uniform1f(gl.getUniformLocation(P,'H'),k===pick?.6:0);
  gl.bindBuffer(gl.ARRAY_BUFFER,q.bp);gl.enableVertexAttribArray(pa);gl.vertexAttribPointer(pa,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,q.bn);gl.enableVertexAttribArray(na);gl.vertexAttribPointer(na,3,gl.FLOAT,false,0,0);gl.drawArrays(gl.TRIANGLES,0,q.nv)});
 if(edges){gl.useProgram(L);const la=gl.getAttribLocation(L,'p');gl.uniformMatrix4fv(gl.getUniformLocation(L,'V'),false,V);gl.uniform3fv(gl.getUniformLocation(L,'C'),[0,0,0]);
  parts.forEach(q=>{if(!q.show||!q.nl)return;gl.uniformMatrix4fv(gl.getUniformLocation(L,'M'),false,q.M);gl.bindBuffer(gl.ARRAY_BUFFER,q.bl);
   gl.enableVertexAttribArray(la);gl.vertexAttribPointer(la,3,gl.FLOAT,false,0,0);gl.drawArrays(gl.LINES,0,q.nl)});
  if(mpts.length){const b=gl.createBuffer();const f=new Float32Array(mpts.length===2?[...mpts[0],...mpts[1]]:[...mpts[0],...mpts[0]]);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,f,gl.STREAM_DRAW);
   gl.disable(gl.DEPTH_TEST);gl.uniformMatrix4fv(gl.getUniformLocation(L,'M'),false,I4);gl.uniform3fv(gl.getUniformLocation(L,'C'),[.9,.1,.1]);gl.vertexAttribPointer(la,3,gl.FLOAT,false,0,0);gl.drawArrays(gl.LINES,0,2);gl.deleteBuffer(b)}}}
function xf(M,x,y,z){return [M[0]*x+M[4]*y+M[8]*z+M[12],M[1]*x+M[5]*y+M[9]*z+M[13],M[2]*x+M[6]*y+M[10]*z+M[14]]}
function ray(ev){const r=cv.getBoundingClientRect(),w=r.width,h=r.height,a=w/h;const sx=((ev.clientX-r.left)/w*2-1)*hh*a,sy=(1-(ev.clientY-r.top)/h*2)*hh;
 const o=[0,1,2].map(i=>tg[i]+R[0][i]*sx+R[1][i]*sy+R[2][i]*rad*3),d=R[2].map(x=>-x);return [o,d]}
function hitTest(ev){const [o,d]=ray(ev);let best=Infinity,bk=-1;
 parts.forEach((q,k)=>{if(!q.show)return;const p=q.tp;for(let i=0;i<p.length;i+=9){const A=xf(q.M,p[i],p[i+1],p[i+2]),Bv=xf(q.M,p[i+3],p[i+4],p[i+5]),Cv=xf(q.M,p[i+6],p[i+7],p[i+8]);
  const e1=[0,1,2].map(j=>Bv[j]-A[j]),e2=[0,1,2].map(j=>Cv[j]-A[j]),pv=cross(d,e2),det=e1[0]*pv[0]+e1[1]*pv[1]+e1[2]*pv[2];if(Math.abs(det)<1e-12)continue;
  const tv=[0,1,2].map(j=>o[j]-A[j]),u=(tv[0]*pv[0]+tv[1]*pv[1]+tv[2]*pv[2])/det;if(u<0||u>1)continue;const qv=cross(tv,e1),v=(d[0]*qv[0]+d[1]*qv[1]+d[2]*qv[2])/det;if(v<0||u+v>1)continue;
  const t=(e2[0]*qv[0]+e2[1]*qv[1]+e2[2]*qv[2])/det;if(t>0&&t<best){best=t;bk=k}}});
 return bk<0?null:{k:bk,p:[0,1,2].map(j=>o[j]+d[j]*best)}}
const info=document.getElementById('info');
let drag=null;cv.addEventListener('contextmenu',e=>e.preventDefault());
cv.addEventListener('mousedown',e=>{drag={b:e.button,x:e.clientX,y:e.clientY,moved:false}});
window.addEventListener('mouseup',e=>{if(drag&&!drag.moved&&drag.b===0)click(e);drag=null});
window.addEventListener('mousemove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>2)drag.moved=true;drag.x=e.clientX;drag.y=e.clientY;
 if(drag.b===0){rot(R[1],-dx*.01);rot(R[0],-dy*.01)}else{const s=2*hh/cv.clientHeight;for(let i=0;i<3;i++)tg[i]-=R[0][i]*dx*s-R[1][i]*dy*s}draw()});
function rot(ax,a){const c=Math.cos(a),s=Math.sin(a),k=norm(ax);R=R.map(v=>{const d=k[0]*v[0]+k[1]*v[1]+k[2]*v[2],cr=cross(k,v);return norm([0,1,2].map(i=>v[i]*c+cr[i]*s+k[i]*d*(1-c)))});
 R[1]=norm(cross(R[2],R[0]));R[0]=norm(cross(R[1],R[2]))}
cv.addEventListener('wheel',e=>{e.preventDefault();hh*=e.deltaY>0?1.1:1/1.1;draw()},{passive:false});
function click(e){const h=hitTest(e);if(measuring){if(!h)return;if(mpts.length>=2)mpts=[];mpts.push(h.p);
  if(mpts.length===2){const d=Math.hypot(...[0,1,2].map(i=>mpts[1][i]-mpts[0][i]));info.textContent='Distance: '+d.toFixed(2)+' mm';info.style.display='block'}else{info.textContent='Pick the second point';info.style.display='block'}
  draw();return}
 select(h?h.k:-1)}
const side=document.getElementById('side');
function select(k){pick=k;[...side.children].forEach((l,i)=>l.classList.toggle('pick',i===k));info.style.display=k<0?'none':'block';if(k>=0)info.textContent=parts[k].name;draw()}
parts.forEach((q,k)=>{const l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=true;
 c.onchange=()=>{q.show=c.checked;draw()};l.append(c,' '+q.name);l.onclick=e=>{if(e.target!==c)select(k)};side.append(l)});
document.getElementById('fit').onclick=fit;document.getElementById('views').onchange=e=>setView(e.target.value);
document.getElementById('edges').onclick=e=>{edges=!edges;e.target.classList.toggle('on',edges);draw()};
document.getElementById('measure').onclick=e=>{measuring=!measuring;mpts=[];e.target.classList.toggle('on',measuring);info.style.display='none';draw()};
const ex=document.getElementById('explode');
if(D.views.length){ex.append(new Option('Collapsed',-1));D.views.forEach((v,i)=>ex.append(new Option(v.name,i)));
 ex.onchange=()=>{const i=+ex.value;parts.forEach((q,k)=>q.M=i<0?I4.slice():D.views[i].mats[k].slice());fit()}}else ex.style.display='none';
window.addEventListener('resize',draw);window.FW={parts,setView,fit,select,hitTest,get pick(){return pick}};setView('iso');
</script></body></html>
"""
