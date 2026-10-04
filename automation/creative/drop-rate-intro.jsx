// Native Higgsedit pilot. Inputs are the approved founder take and owned logo.
// This renderer has no publishing credentials or scheduling side effects.
import fs from 'node:fs/promises';

export default async ({ project }) => {
  const duration = Number(process.env.PILOT_DURATION || '14.783167');
  if (!Number.isFinite(duration) || duration < 10 || duration > 25) throw Error('invalid_voice_duration');
  const NAVY = '#071B3F', CYAN = '#08C5DE', GOLD = '#F7C653', CREAM = '#F6F3EC';
  const slides = [
    { label:'THE COLLECTOR JOURNAL', lines:['Every collection', 'has a story.'], detail:'What makes yours worth telling?', tag:'WELCOME TO DROP RATE', pale:true },
    { label:'CARDS / CHARACTERS / CULTURE', lines:['The card.', 'The character.', 'The story.'], detail:'A closer look at what collectors care about.', tag:'GO BEYOND THE PRICE TAG', pale:false },
    { label:'FIND YOUR WORLD', lines:['Pokémon.', 'One Piece.', 'Dragon Ball.', 'Naruto.'], detail:'Four worlds. One collecting community.', tag:'FOLLOW THE STORY', pale:true },
    { label:'YOUR NEXT CHAPTER', lines:['What’s your', 'next grail?'], detail:'Tell us what you collect.', tag:'FOLLOW @DROPRATETCG', pale:false },
  ];
  const composeSlide = (s, logo, height, animated=false, sceneDuration=1) => {
    const fg=s.pale?NAVY:CREAM, bg=s.pale?CREAM:NAVY;
    const top=height===1920?310:230;
    const titleSize=s.lines.length===4?96:100;
    const captionsSpace=height===1920?220:0;
    return <frame layout="none" width={1080} height={height} background={bg}>
      <rect x={0} y={0} width={1080} height={18} fill={CYAN}/>
      <rect x={76} y={96} width={8} height={42} fill={GOLD}/>
      <text x={105} y={99} width={860} height={44} fontFamily="Montserrat" fontWeight={700} fontSize={25} letterSpacing={3} color={fg}>{s.label}</text>
      <frame x={76} y={top} width={938} height={550} layout="none" animate={animated?[{property:'offsetY',from:24,to:0,at:0,duration:0.4},{property:'opacity',from:0,to:1,at:0,duration:0.35}]:[]}>
        {s.lines.map((line,i)=><text x={0} y={i*(titleSize+15)} width={936} height={132} fontFamily="Montserrat" fontWeight={800} fontSize={titleSize} letterSpacing={-5} color={i===s.lines.length-1?(s.pale?NAVY:CYAN):fg}>{line}</text>)}
      </frame>
      <path x={775} y={height-570} width={240} height={290} d="M 45 0 L 235 34 L 200 285 L 0 247 Z" fill={s.pale?'#EAE4D8':'#12355E'} stroke={{color:s.pale?'#DBD3C2':'#1D4D76',width:3}}/>
      <path x={853} y={height-535} width={100} height={160} d="M 54 0 L 64 55 L 100 79 L 62 96 L 48 160 L 38 99 L 0 77 L 38 56 Z" fill={GOLD}/>
      <text x={80} y={height-495-captionsSpace} width={700} height={104} fontFamily="Montserrat" fontWeight={500} fontSize={32} lineHeight={1.35} color={fg}>{s.detail}</text>
      <rect x={80} y={height-352-captionsSpace} width={690} height={3} fill={s.pale?'#D7D3CB':'#25415E'}/>
      <text x={80} y={height-315-captionsSpace} width={760} height={55} fontFamily="Montserrat" fontWeight={700} fontSize={27} letterSpacing={1.2} color={s.pale?NAVY:GOLD}>{s.tag}</text>
      <rect x={74} y={height-185} width={180} height={124} radius={8} fill="#FFFFFF"/>
      <media x={79} y={height-180} width={170} height={114} file={logo} fit="contain"/>
      <text x={285} y={height-142} width={610} height={38} fontFamily="Montserrat" fontWeight={600} fontSize={24} color={fg}>DROP RATE · COLLECT WHAT YOU LOVE</text>
    </frame>;
  };
  await fs.mkdir('/home/user/output',{recursive:true});
  for (const height of [1350,1920]) {
    const p=await project({dir:`/home/user/pilot-${height}`,size:`1080x${height}`,fps:30,background:NAVY});
    const logo=await p.add('/home/user/logo.png');
    const d=height===1920?duration/slides.length:1;
    for(let i=0;i<slides.length;i++) {
      p.compose(composeSlide(slides[i],logo,height,height===1920,d),{at:i*d,dur:d,name:`Slide ${i+1}`});
      await p.frame(i*d+Math.min(0.6,d/2),`/home/user/output/${height}-${i+1}.png`);
    }
    if(height===1920) {
      const voice=await p.add('/home/user/voice.wav');
      p.cut(voice,{from:0,dur:duration,at:0});
      await p.render('/home/user/output/clean.mp4',{bitrate:8000000,concurrency:2});
    }
  }
};
