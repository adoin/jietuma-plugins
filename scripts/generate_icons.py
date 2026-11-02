"""Regenerate the plugin-owned SVG, PNG and multi-resolution Windows ICO assets.

Requires Pillow only when editing icons; release packaging uses committed assets.
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICONS = {
    'spreadsheet': ('#22845F', [('rect',(58,58,198,198)),('line',(58,104,198,104)),('line',(105,58,105,198)),('line',(151,104,151,198)),('line',(58,151,198,151))]),
    'code-highlight': ('#6155B9', [('line',(91,83,50,128,91,173)),('line',(165,83,206,128,165,173)),('line',(145,66,111,190))]),
    'clipboard-backup': ('#7050A0', [('rect',(64,59,192,198)),('rect',(100,47,156,76)),('line',(128,101,128,165)),('line',(103,140,128,165,153,140))]),
    'format-inspector': ('#B17B24', [('circle',(54,51,161,158)),('line',(146,146,199,199)),('line',(79,88,137,88)),('line',(79,119,119,119))]),
    'json-pretty': ('#298B8D', [('line',(97,58,77,58,77,110,59,128,77,146,77,198,97,198)),('line',(159,58,179,58,179,110,197,128,179,146,179,198,159,198)),('line',(105,134,123,151,154,112))]),
    'json-preview': ('#3A79BB', [('line',(93,57,73,57,73,105,55,124,73,143,73,192,93,192)),('line',(163,57,183,57,183,105,201,124,183,143,183,192,163,192)),('circle',(104,104,152,152))]),
    'markdown-preview': ('#476889', [('line',(57,170,57,88,94,131,131,88,131,170)),('line',(179,88,179,170)),('line',(154,145,179,170,204,145))]),
    'notes-tags': ('#B96B35', [('polygon',(55,60,134,60,203,129,128,204,55,131)),('circle',(78,82,100,104))]),
    'rtf-preview': ('#AE5867', [('polygon',(68,48,157,48,193,86,193,207,68,207)),('line',(155,48,155,88,193,88)),('line',(93,119,167,119)),('line',(93,148,167,148)),('line',(93,177,143,177))]),
    'script-transform': ('#8052B1', [('rect',(48,62,208,194)),('line',(75,99,104,126,75,153)),('line',(129,154,177,154))]),
    'secret-filter': ('#AA5257', [('polygon',(128,46,195,73,189,146,163,185,128,209,93,185,67,146,61,73)),('rect',(98,113,158,161)),('line',(108,113,108,96,118,84,138,84,148,96,148,113))]),
    'source-exclusions': ('#637589', [('rect',(49,61,207,194)),('line',(49,98,207,98)),('line',(95,119,163,176)),('line',(163,119,95,176))]),
}

def main():
    for plugin, (color, shapes) in ICONS.items():
        image=Image.new('RGBA',(1024,1024));draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((20,20,1004,1004),radius=220,fill=color)
        svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="5" y="5" width="246" height="246" rx="55" fill="{color}"/><g stroke="#fff" fill="none" stroke-width="10" stroke-linecap="round" stroke-linejoin="round">']
        for kind,points in shapes:
            p=tuple(v*4 for v in points)
            if kind=='line':
                draw.line(p,fill='white',width=40,joint='curve')
                for x,y in zip(p[::2],p[1::2]):draw.ellipse((x-20,y-20,x+20,y+20),fill='white')
                svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in zip(points[::2],points[1::2]))+'"/>')
            elif kind=='rect':
                draw.rounded_rectangle(p,radius=20,outline='white',width=40)
                x,y,r,b=points;svg.append(f'<rect x="{x}" y="{y}" width="{r-x}" height="{b-y}" rx="5"/>')
            elif kind=='circle':
                draw.ellipse(p,outline='white',width=40)
                x,y,r,b=points;svg.append(f'<ellipse cx="{(x+r)/2}" cy="{(y+b)/2}" rx="{(r-x)/2}" ry="{(b-y)/2}"/>')
            else:
                draw.line(p+p[:2],fill='white',width=40,joint='curve')
                svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in zip(points[::2],points[1::2]))+'"/>')
        svg.append('</g></svg>')
        folder=ROOT/'plugins'/plugin
        (folder/'icon.svg').write_text(''.join(svg)+'\n',encoding='utf-8')
        small=image.resize((256,256),Image.Resampling.LANCZOS)
        small.save(folder/'icon.png')
        small.save(folder/'plugin.ico',sizes=[(n,n) for n in [16,24,32,48,64,128,256]])
        print(plugin)

if __name__=='__main__': main()
