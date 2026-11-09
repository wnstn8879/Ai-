import React, {useEffect,useState} from 'react';
import {SafeAreaView,ScrollView,Text,TextInput,Pressable,View,Alert,StyleSheet} from 'react-native';
import {StatusBar} from 'expo-status-bar';
const API=process.env.EXPO_PUBLIC_API_URL || 'http://10.0.2.2:8000';
async function request(path,method='GET',body){
 const response=await fetch(API+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 if(!response.ok) throw new Error(await response.text());
 return response.json();
}
export default function App(){
 const [rooms,setRooms]=useState([]),[room,setRoom]=useState(null),[saves,setSaves]=useState([]);
 const [title,setTitle]=useState('사라진 왕국'),[rules,setRules]=useState('설정을 임의로 변경하지 않는다.');
 const [mode,setMode]=useState('solo'),[input,setInput]=useState(''),[label,setLabel]=useState('중요한 선택 전');
 const [busy,setBusy]=useState(false);
 const run=async fn=>{setBusy(true);try{await fn();}catch(e){Alert.alert('오류',String(e.message));}finally{setBusy(false);}};
 const refresh=async()=>setRooms(await request('/rooms'));
 const open=async id=>{const [r,s]=await Promise.all([request('/rooms/'+id),request('/rooms/'+id+'/saves')]);setRoom(r);setSaves(s);};
 useEffect(()=>{refresh().catch(()=>Alert.alert('서버 연결 실패','EXPO_PUBLIC_API_URL 설정을 확인하세요.'));},[]);
 const create=()=>run(async()=>{const r=await request('/rooms','POST',{title,world_rules:rules,characters:[],mode});await refresh();await open(r.id);});
 const send=()=>run(async()=>{if(!input.trim())return;await request('/rooms/'+room.id+'/turns','POST',{actor:'나',content:input.trim()});setInput('');await open(room.id);});
 const save=()=>run(async()=>{await request('/rooms/'+room.id+'/saves','POST',{label,message_index:room.messages.length});await open(room.id);});
 const resume=s=>run(async()=>{const r=await request('/saves/'+s.id+'/resume','POST');await refresh();await open(r.id);});
 const fork=index=>run(async()=>{const r=await request('/rooms/'+room.id+'/forks','POST',{title:room.title+' · 다른 선택',message_index:index});await refresh();await open(r.id);});
 const btn=(text,fn)=><Pressable disabled={busy} onPress={fn} style={styles.button}><Text style={styles.buttonText}>{text}</Text></Pressable>;
 return <SafeAreaView style={styles.root}><StatusBar style="light"/><ScrollView contentContainerStyle={styles.body}><Text style={styles.title}>StoryVerse AI</Text>
 {room?<><Text style={styles.heading}>{room.title}</Text><Text style={styles.muted}>{room.mode==='solo'?'혼자 플레이':'멀티플레이'} · 메시지 {room.messages.length}개</Text>
 {btn('← 내 스토리',()=>{setRoom(null);refresh();})}
 {room.messages.map((m,i)=><View key={m.id} style={styles.card}><Text style={styles.text}>{i+1}. {m.actor}: {m.content}</Text>{btn('이 지점부터 새로 시작',()=>fork(i+1))}</View>)}
 <TextInput style={styles.input} value={input} onChangeText={setInput} placeholder="행동이나 대사 입력" placeholderTextColor="#999"/>
 {btn('AI와 대화하기 (자동 저장)',send)}
 <TextInput style={styles.input} value={label} onChangeText={setLabel} placeholder="저장 이름" placeholderTextColor="#999"/>
 {btn('현재 지점 수동 저장',save)}
 <Text style={styles.heading}>저장 지점</Text>
 {saves.map(s=><View style={styles.card} key={s.id}><Text style={styles.text}>{s.label} · {s.message_index}번째 메시지</Text>{btn('이 지점부터 이어하기',()=>resume(s))}</View>)}
 {btn('처음부터 다른 이야기 만들기',()=>fork(0))}
 </>:<><Text style={styles.heading}>새 스토리</Text><TextInput style={styles.input} value={title} onChangeText={setTitle}/><TextInput multiline style={styles.input} value={rules} onChangeText={setRules}/>
 {btn(mode==='solo'?'모드: 혼자 플레이':'모드: 멀티플레이',()=>setMode(mode==='solo'?'multiplayer':'solo'))}{btn('새 스토리 시작',create)}
 <Text style={styles.heading}>내 스토리 · 이어하기</Text>{rooms.map(r=><View style={styles.card} key={r.id}><Text style={styles.text}>{r.title} · {r.messages.length}개 메시지</Text>{btn('이어서 하기',()=>run(()=>open(r.id)))}</View>)}</>}
 <Text style={styles.muted}>AI 대화는 서버의 OPENAI_API_KEY 설정이 필요합니다. 실시간 멀티플레이와 로그인은 후속 구현 대상입니다.</Text>
 </ScrollView></SafeAreaView>;
}
const styles=StyleSheet.create({root:{flex:1,backgroundColor:'#101827'},body:{padding:20,gap:12},title:{fontSize:28,color:'white',fontWeight:'bold'},heading:{fontSize:19,color:'white',fontWeight:'bold',marginTop:10},muted:{color:'#a3adbc'},input:{borderWidth:1,borderColor:'#596579',color:'white',borderRadius:10,padding:12,minHeight:48},card:{backgroundColor:'#263245',padding:12,borderRadius:10,gap:8},text:{color:'white'},button:{backgroundColor:'#6265d9',padding:11,borderRadius:9,alignItems:'center'},buttonText:{color:'white',fontWeight:'600'}});
