"""Measurement workflow and read-only summaries of committed records."""
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from contextlib import nullcontext
from xml.sax.saxutils import escape

import session_management as sessions
from recording import FS, _readonly_connection, _sync_directory

DURATIONS = {'手动结束': None, '1 分钟': 60, '3 分钟': 180, '5 分钟': 300}
_pdf_lock = threading.Lock()


def owner_label(metadata):
    uid = metadata.get('cloud_owner_id')
    if not uid:
        return '未分配（云端由管理员分配）'
    return str(metadata.get('cloud_owner_name') or uid)


def preflight_checks(*, source, port, storage, cloud, owner_name):
    rows = []
    def add(key, title, detail, blocking=False):
        rows.append(dict(key=key, title=title, detail=detail, blocking=blocking))
    add('owner', '记录归属', owner_name or '未分配')
    add('port', '数据来源', ('串口 '+port) if source=='serial' and port else
        '未选择采集端口' if source=='serial' else '本地模拟' if source=='demo' else '文件回放', source=='serial' and not port)
    state = storage.get('state','unknown')
    free = storage.get('free_bytes')
    add('storage','存储空间', ('剩余 %.0f MB' % (free/1048576) if isinstance(free,(int,float)) else '空间未确认')+
        ('，不足以安全开始' if state=='critical' else '，空间偏低' if state=='warning' else ''), state not in ('ok','warning'))
    add('signal','信号检查', '待检查：开始接收后自动判断实采模式和信号质量' if source=='serial' else '模拟或回放，不作为本次人体测量')
    add('cloud','云端上传', {'online':'设备授权已验证，可手动上传','unauthorized':'设备凭据失效；可先保存在本机'}.get(cloud.get('connection'),'离线或检查中；可先保存在本机'))
    return rows


class MeasurementStats:
    """Bounded statistics; consume each analysed batch once, never UI polling."""
    def __init__(self):
        self.real = self.usable = self.weight = 0
        self.total = 0.
        self.low = self.high = None

    def observe(self, batch, result):
        if batch.source != 'serial' or not any(p.mode==0 for p in batch.points): return
        values=result.get('measurement')
        if not isinstance(values,dict):return
        self.real += values['analyzed_real_samples']
        self.usable += values['usable_real_samples']
        if not values['hr_weight']:return
        self.total += values['hr_total']
        self.weight += values['hr_weight']
        self.low = values['hr_min'] if self.low is None else min(self.low,values['hr_min'])
        self.high = values['hr_max'] if self.high is None else max(self.high,values['hr_max'])

    def snapshot(self):
        return dict(schema_version=1, analyzed_real_samples=self.real, usable_real_samples=self.usable,
                    hr=dict(mean=self.total/self.weight,min=self.low,max=self.high,window_samples=self.weight)
                    if self.weight else None)


def build_summary(data_dir, sid, *, _locked=False):
    # Coordinate with trash/export. Never write to or recover the input record.
    with (nullcontext() if _locked else sessions._management_lock(sessions._root(data_dir))):
        directory = sessions._directory(sessions._root(data_dir),sid)
        metadata = sessions._metadata(directory)
        if metadata.get('status') == 'recording': raise ValueError('请先停止采集并等待保存完成')
        stats = None
        with _readonly_connection(directory/'index.sqlite') as db:
            row = db.execute("SELECT detail_json FROM events WHERE kind='measurement_summary' ORDER BY event_id DESC LIMIT 1").fetchone()
            if row:
                candidate=json.loads(row[0])
                if (metadata.get('status')=='complete' and isinstance(candidate,dict)
                        and candidate.get('schema_version') == 1): stats=candidate
        from classification_review import classification_details
        classified = classification_details(data_dir,sid,limit=1)
        quality = metadata.get('quality') or {}
        total = metadata.get('sample_count',0)
        valid = quality.get('valid_samples')
        hr = stats.get('hr') if stats and metadata.get('source')=='serial' else None
        return dict(session_id=sid, owner_id=metadata.get('cloud_owner_id'),owner_name=owner_label(metadata),
            source=metadata.get('source','unknown'),started_utc=metadata.get('started_utc'),
            time_trusted=bool((metadata.get('time_info') or {}).get('trusted')),
            status=metadata.get('status'),error=metadata.get('error'),end_reason=metadata.get('end_reason'),
            requested_duration_s=metadata.get('requested_duration_s'),sample_count=total,duration_s=total/FS,
            valid_ratio=valid/total if total and isinstance(valid,int) else None,
            quality_counts=quality,analysis_stats=stats,hr=hr,
            classification_counts=classified['counts'],classification_rejected=classified['rejected'],
            classification_note=classified['note'],classification_enabled=(metadata.get('classification') or {}).get('enabled'),
            note='有效采样比例仅依据 ADC 范围与无效标记，不等同可分析比例。质量通过时间逐点累计；心率按通过质量门控的有效实采 RR 间期加权统计。N 类包含束支阻滞；模型输出不作为临床诊断。')


def summary_lines(summary):
    s=summary
    state={'complete':'已完成保存','failed':'保存或采集异常','incomplete':'未完整结束','recovered_incomplete':'中断后恢复'}.get(s['status'],s['status'])
    rows=[('保存状态',state),('记录归属',s['owner_name']),('记录编号',s['session_id']),
          ('数据来源',{'serial':'STM32 串口（实采与模拟见下方统计）','demo':'本地模拟','replay':'文件回放'}.get(s['source'],'未知')),
          ('开始时间',str(s.get('started_utc') or '未知')+('' if s['time_trusted'] else '（设备时间未核准）')),
          ('记录时长',f"{s['duration_s']:.1f} 秒 / {s['sample_count']:,} 点（按采样点数）"),
          ('计划时长',f"{s['requested_duration_s']:g} 秒" if s.get('requested_duration_s') else '手动结束或旧记录未提供'),
          ('结束原因',{'duration_complete':'定时结束','stopped':'手动结束','storage_low':'空间不足'}.get(s.get('end_reason'),s.get('end_reason') or '未知')),
          ('有效采样比例',f"{s['valid_ratio']:.1%}" if s['valid_ratio'] is not None else '无数据或旧记录未提供')]
    q=s['quality_counts']
    rows.append(('实采 / 模拟点数',f"{q.get('real_mode_samples','未知')} / {q.get('simulated_mode_samples','未知')}"))
    rows.append(('无效标记 / 饱和点',f"{q.get('invalid_marker_samples','未知')} / {q.get('saturated_samples','未知')}"))
    stats=s.get('analysis_stats')
    rows.append(('质量门控通过', f"{stats['usable_real_samples']/FS:.1f} 秒 / 已分析实采 {stats['analyzed_real_samples']/FS:.1f} 秒" if stats else '未提供统计或保存异常，无法核对'))
    hr=s.get('hr')
    rows.append(('有效 RR 心率',f"均值 {hr['mean']:.1f}，最低 {hr['min']:.1f}，最高 {hr['max']:.1f} 次/分" if hr else '无有效实采心率统计'))
    counts=s['classification_counts']
    rows.append(('已保存分类',f"N {counts['N']} / S {counts['S']} / V {counts['V']}" if sum(counts.values()) else '未获得有效分类结果'))
    if s.get('error'):rows.append(('异常信息',str(s['error'])))
    return rows


def export_pdf(data_dir,sid,output_path):
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:
        raise RuntimeError('PDF 组件未安装；树莓派请安装 python3-reportlab，或按 requirements-pi.txt 安装依赖') from exc
    with sessions._export_guard(data_dir,sid,output_path,'.pdf') as (root,_,target,_):
        summary=build_summary(data_dir,sid,_locked=True)
        with tempfile.TemporaryDirectory(prefix='.ecg-report-',dir=target.parent) as temporary, _pdf_lock:
            if 'ECGReport' not in pdfmetrics.getRegisteredFontNames():
                candidates=[os.getenv('ECG_REPORT_FONT',''),'/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
                    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',r'C:\Windows\Fonts\msyh.ttc',r'C:\Windows\Fonts\simsun.ttc']
                font=next((p for p in candidates if p and Path(p).is_file()),None)
                if not font: raise RuntimeError('缺少中文报告字体，请安装 fonts-wqy-microhei 或设置 ECG_REPORT_FONT')
                pdfmetrics.registerFont(TTFont('ECGReport',font,subfontIndex=0))
            style=ParagraphStyle('body',fontName='ECGReport',fontSize=10,leading=16,wordWrap='CJK',textColor=colors.HexColor('#243a43'))
            title=ParagraphStyle('title',parent=style,fontSize=21,leading=29,textColor=colors.HexColor('#126958'),spaceAfter=12)
            def p(value):return Paragraph(escape(str(value)),style)
            story=[Paragraph('心电测量总结',title),p('本地采集记录 · 辅助分析'),Spacer(1,14)]
            table=Table([[p(k),p(v)] for k,v in summary_lines(summary)],colWidths=[105,405],hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#edf5f2')),
                ('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#dce7e4')),('LEFTPADDING',(0,0),(-1,-1),9),
                ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            story.extend([table,Spacer(1,15),p(summary['note']),Spacer(1,6),p('此报告来自本地已保存记录，不代表云端分析或上传确认。采样点数时长不包含断流期间的实际等待时间。')])
            staged=Path(temporary)/'report.pdf'
            def footer(canvas,doc):
                canvas.setFont('ECGReport',8);canvas.setFillColor(colors.HexColor('#61756d'))
                canvas.drawString(42,25,'心电采集终端 · 第 %s 页'%doc.page)
            SimpleDocTemplate(str(staged),pagesize=(595,842),leftMargin=42,rightMargin=42,topMargin=36,bottomMargin=42,
                              title='心电测量总结',author='ECG Terminal').build(story,onFirstPage=footer,onLaterPages=footer)
            sessions._export_target(root,target,'.pdf')
            os.replace(staged,target);_sync_directory(target.parent)
    return str(target)
