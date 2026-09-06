"""Small Resolve API doubles. No native libraries, installed runtime or project access."""
import copy
import uuid

class Media:
    def __init__(self, path='', fps=24):
        self.uid=uuid.uuid4().hex
        self.props={'File Path':str(path),'FPS':str(fps)}
    def GetUniqueId(self):return self.uid
    def GetClipProperty(self, key=None):return self.props.get(key) if key else dict(self.props)
    def SetClipProperty(self,key,value):self.props[key]=value;return True

class Clip:
    def __init__(self,start=0,end=100,media=None,source=0,name='clip',kind='video',track=1):
        self.uid=uuid.uuid4().hex;self.start=start;self.end=end;self.media=media or Media()
        self.source=source;self.name=name;self.kind=kind;self.track=track
        self.props={'ZoomX':1.0,'ZoomY':1.0};self.enabled=True;self.color='';self.fusion=None
    def GetUniqueId(self):return self.uid
    def GetName(self):return self.name
    def GetStart(self):return self.start
    def GetEnd(self):return self.end
    def GetDuration(self):return self.end-self.start
    def GetMediaPoolItem(self):return self.media
    def GetSourceStartFrame(self):return self.source
    def GetSourceEndFrame(self):return self.source+self.GetDuration()-1
    def GetLeftOffset(self):return self.source
    def GetRightOffset(self):return 0
    def GetProperty(self,key=None):return self.props.get(key) if key else dict(self.props)
    def SetProperty(self,key,value):self.props[key]=value;return True
    def GetClipEnabled(self):return self.enabled
    def SetClipEnabled(self,value):self.enabled=value;return True
    def GetClipColor(self):return self.color
    def SetClipColor(self,value):self.color=value;return True
    def GetFusionCompCount(self):return int(self.fusion is not None)
    def GetFusionCompByIndex(self,index):return self.fusion
    def CopyGrades(self,items):return True

class Timeline:
    def __init__(self,project,name='Original',clips=None,start=0,fps=24):
        self.project=project;self.name=name;self.clips=clips or [];self.start=start;self.fps=fps
        self.uid=uuid.uuid4().hex;self.current='00:00:00:00';self.start_tc='00:00:00:00';self.markers={}
        self.disabled=set();self.locked=set();self.delete_calls=0
    def GetUniqueId(self):return self.uid
    def GetName(self):return self.name
    def GetStartFrame(self):return self.start
    def GetEndFrame(self):return max([self.start]+[c.end for c in self.clips])
    def GetStartTimecode(self):return self.start_tc
    def GetCurrentTimecode(self):return self.current
    def SetCurrentTimecode(self,tc):self.current=tc;return True
    def GetSetting(self,key):return {'timelineFrameRate':str(self.fps),'timelineResolutionWidth':'1920','timelineResolutionHeight':'1080'}.get(key)
    def GetTrackCount(self,kind):return max([0]+[c.track for c in self.clips if c.kind==kind])
    def GetTrackName(self,kind,index):return '%s %d'%(kind,index)
    def GetItemListInTrack(self,kind,index):return sorted([c for c in self.clips if c.kind==kind and c.track==index],key=lambda c:c.start)
    def GetIsTrackEnabled(self,kind,index):return (kind,index) not in self.disabled
    def GetIsTrackLocked(self,kind,index):return (kind,index) in self.locked
    def GetMarkers(self):return dict(self.markers)
    def AddMarker(self,frame,color,name,note,duration,customData=''):
        if frame in self.markers:return False
        self.markers[frame]=dict(color=color,name=name,note=note,duration=duration,customData=customData);return True
    def DeleteMarkerAtFrame(self,frame):return self.markers.pop(frame,None) is not None
    def DuplicateTimeline(self,name):
        clips=[]
        for c in self.clips:
            cloned=copy.copy(c);cloned.uid=uuid.uuid4().hex;cloned.props=dict(c.props);clips.append(cloned)
        t=Timeline(self.project,name,clips,self.start,self.fps)
        t.current=self.current;t.start_tc=self.start_tc;t.markers=copy.deepcopy(self.markers)
        t.disabled=set(self.disabled);t.locked=set(self.locked);self.project.timelines.append(t);return t
    def DeleteClips(self,items,ripple=False):
        self.delete_calls+=1
        for item in items:
            if item in self.clips:self.clips.remove(item)
        return True
    def SetClipsLinked(self,items,linked):return True

class Pool:
    def __init__(self,project):self.project=project;self.append_limit=None
    def AppendToTimeline(self,requests):
        result=[]
        for r in requests[:self.append_limit]:
            c=Clip(r['recordFrame'],r['recordFrame']+r['endFrame']-r['startFrame']+1,r['mediaPoolItem'],r['startFrame'],kind='video' if r['mediaType']==1 else 'audio',track=r['trackIndex'])
            self.project.current.clips.append(c);result.append(c)
        return result

class Project:
    def __init__(self,clips=None):
        self.current=Timeline(self,clips=clips);self.timelines=[self.current];self.pool=Pool(self)
    def GetCurrentTimeline(self):return self.current
    def SetCurrentTimeline(self,t):self.current=t;return True
    def GetTimelineCount(self):return len(self.timelines)
    def GetTimelineByIndex(self,i):return self.timelines[i-1]
    def GetMediaPool(self):return self.pool
    def GetSetting(self,key):return {'timelineFrameRate':'24','timelineResolutionWidth':'1920','timelineResolutionHeight':'1080'}.get(key)
    def GetName(self):return 'Test project'

class Resolve:
    def __init__(self,project):self.project=project
    def GetProjectManager(self):return self
    def GetCurrentProject(self):return self.project
    def GetVersionString(self):return '21 test'
    def GetProductName(self):return 'DaVinci Resolve'
