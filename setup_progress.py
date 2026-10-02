"""Stdlib-only setup stages and subprocess liveness, without invented percentages."""
import os,queue,shutil,subprocess,sys,threading,time

class SetupProgress:
 def __init__(self,total=3,stream=None,clock=time.monotonic):
  self.total=total;self.stream=stream or sys.stdout;self.clock=clock;self.started=clock();self.step=0;self.phase='Starting';self.last_output=self.started;self.tick=0;self.drawn=False;self.tty=getattr(self.stream,'isatty',lambda:False)()
 def line(self):
  done=max(0,self.step-1);width=15;filled=round(width*done/self.total)
  bar='='*filled+'-'*(width-filled);elapsed=int(self.clock()-self.started);quiet=int(self.clock()-self.last_output);spin='|/-\\'[self.tick%4]
  if self.tty:
   cols=shutil.get_terminal_size((100,24)).columns;phase=self.phase[:max(10,cols-62)]
   return f'[{bar}] {self.step}/{self.total} {phase} {spin} | {elapsed}s | output {quiet}s ago'
  return f'[{bar}] Step {self.step}/{self.total}: {self.phase} {spin} | elapsed {elapsed}s | last output {quiet}s ago'
 def width(self):return max(20,shutil.get_terminal_size((100,24)).columns-1)
 def status(self):
  self.tick+=1;line=self.line()
  if self.tty:self.stream.write('\r'+line[:self.width()].ljust(self.width()));self.drawn=True
  else:self.stream.write('[setup] '+line+'\n')
  self.stream.flush()
 def output(self,text):
  if self.drawn:self.stream.write('\r'+' '*self.width()+'\r');self.drawn=False
  self.stream.write(text if text.endswith('\n') else text+'\n');self.stream.flush();self.last_output=self.clock()
 def stage(self,step,phase):
  self.step=step;self.phase=phase;self.last_output=self.clock();self.status()
 def finish(self):
  if self.drawn:self.stream.write('\r'+' '*self.width()+'\r');self.drawn=False
  self.stream.write('[===============] Setup complete | elapsed '+str(int(self.clock()-self.started))+'s\n');self.stream.flush()
 def run(self,args,phase,env=None):
  self.phase=phase;self.status();q=queue.Queue()
  proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env)
  def reader():
   try:
    for line in proc.stdout:q.put(line)
   finally:q.put(None)
  thread=threading.Thread(target=reader,daemon=True);thread.start();last_status=self.clock()
  try:
   while True:
    try:line=q.get(timeout=.25)
    except queue.Empty:line=''
    if line is None:break
    if line:
     self.output(line)
     if 'Installing collected packages:' in line:self.phase='Installing packages (pip has no percentage)'
     elif 'Downloading ' in line:self.phase='Downloading packages'
     elif 'Requirement already satisfied:' in line:self.phase='Checking existing packages'
    interval=1 if self.tty else 10
    if self.clock()-last_status>=interval:self.status();last_status=self.clock()
   code=proc.wait();thread.join(timeout=1)
   if code:raise subprocess.CalledProcessError(code,args)
  except KeyboardInterrupt:
   proc.terminate()
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
   raise
  finally:
   proc.stdout.close()
   if self.drawn:self.stream.write('\r'+' '*self.width()+'\r');self.stream.flush();self.drawn=False
