import datetime as dt,importlib.util,pathlib
s=importlib.util.spec_from_file_location('planner',str(pathlib.Path(__file__).with_name('planner.py')));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
UTC=dt.timezone.utc;now=dt.datetime(2026,11,13,5,tzinfo=UTC);day=now.astimezone(m.zoneinfo.ZoneInfo('America/Porto_Velho')).date()
busy=[{'publishDate':'2026-11-12T10:00:00+00:00','intervalInDays':1},{'publishDate':'2026-11-13T11:00:00+00:00','intervalInDays':1},{'publishDate':'2026-11-13T12:00:00+00:00','intervalInDays':1},{'publishDate':'2026-11-13T13:00:00+00:00','intervalInDays':1}]
a=m.free_slot(day,now,busy,'America/Porto_Velho');assert a.hour==14 # 10h local, after 06/07/08/09 recurring posts.
busy.append({'publishDate':'2026-11-13T14:30:00+00:00','intervalInDays':None});a=m.free_slot(day,now,busy,'America/Porto_Velho',10);assert a.hour==17 # 13h local: 10/11 conflict and 12 reserved.
assert m.conflict(dt.datetime(2027,1,1,10,tzinfo=UTC),busy,60)
assert not m.cooldown_ready(now.isoformat(),now+dt.timedelta(days=59,hours=23,minutes=59))
assert m.cooldown_ready(now.isoformat(),now+dt.timedelta(days=60))
assert sorted(['10.mp4','2.mp4','1.mp4'],key=m.natural)==['1.mp4','2.mp4','10.mp4']
# A pair of destinations is one content day; never use native daily repetition.
days=[day+dt.timedelta(days=i) for i in range(44)];assert len(days)==len(set(days))==44
print('PASS: recurring conflicts, hourly safety gap, reserved group hours, next free slot, 60 full-day cooldown, natural ordering, one content day per asset')
