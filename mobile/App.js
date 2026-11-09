import React, {useState} from 'react';
import {SafeAreaView, View, Text, TextInput, Pressable, ScrollView, StyleSheet} from 'react-native';
import {StatusBar} from 'expo-status-bar';
export default function App(){
 const [title,setTitle]=useState('사라진 왕국');
 const [rules,setRules]=useState('왕국의 비밀을 찾는다. 설정을 임의로 변경하지 않는다.');
 const [messages,setMessages]=useState([]);
 const [input,setInput]=useState('');
 const [branches,setBranches]=useState([]);
 const send=()=>{if(input.trim()){setMessages([...messages,{actor:'나',content:input.trim()}]);setInput('');}};
 const fork=()=>setBranches([...branches,{title:`${title} · 평행세계 ${branches.length+1}`,messages:messages.map(m=>({...m}))}]);
 return <SafeAreaView style={s.root}><StatusBar style="light"/><ScrollView contentContainerStyle={s.body}><Text style={s.heading}>StoryVerse AI</Text><Text style={s.muted}>나만의 세계를 만들고, 다른 결말로 분기하세요.</Text><Text style={s.label}>스토리 제목</Text><TextInput style={s.input} value={title} onChangeText={setTitle}/><Text style={s.label}>세계관 규칙</Text><TextInput multiline style={[s.input,{height:90}]} value={rules} onChangeText={setRules}/><Text style={s.label}>스토리 기록 (로컬 데모)</Text>{messages.map((m,i)=><View key={i} style={s.bubble}><Text style={s.text}>{m.actor}: {m.content}</Text></View>)}<TextInput style={s.input} value={input} onChangeText={setInput} placeholder="다음 행동을 입력하세요" placeholderTextColor="#888"/><Pressable style={s.button} onPress={send}><Text style={s.buttonText}>대화 기록 추가</Text></Pressable><Pressable style={s.button} onPress={fork}><Text style={s.buttonText}>현재 시점에서 평행세계 만들기</Text></Pressable><Text style={s.label}>분기된 세계: {branches.length}</Text>{branches.map((b,i)=><Text style={s.text} key={i}>{b.title} ({b.messages.length}개 메시지)</Text>)}<Text style={s.muted}>AI 응답·서버 연결·영구 저장은 후속 개발 대상입니다.</Text></ScrollView></SafeAreaView>
}
const s=StyleSheet.create({root:{flex:1,backgroundColor:'#111827'},body:{padding:22,gap:12},heading:{fontSize:29,fontWeight:'bold',color:'#fff'},muted:{color:'#9ca3af',lineHeight:21},label:{color:'#e5e7eb',fontWeight:'bold',marginTop:10},input:{borderColor:'#4b5563',borderWidth:1,borderRadius:10,padding:12,color:'#fff'},button:{backgroundColor:'#6366f1',padding:15,borderRadius:10,alignItems:'center'},buttonText:{color:'#fff',fontWeight:'bold'},bubble:{backgroundColor:'#374151',padding:12,borderRadius:10},text:{color:'#fff'}});