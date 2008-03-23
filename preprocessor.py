import os, fnmatch

class Resolver:
  def isDefined(self, key):
    return False
  def resolveValue(self, key):
    return ""

class Control:
  parent = None
  processor = None

  def __init__(self, processor):
    self.processor = processor

  def handleDirective(self, verb, line):
    if self.parent:
      return self.parent.handleDirective(verb, line)
    else:
      raise IOError, "Unknown processing directive " + verb

  def handleLine(self, line):
    if self.parent:
      self.parent.handleLine(line)
    else:
      self.processor.write(self.processor.processDefines(line))

  def close(self):
    pass

class BaseControl(Control):
  def handleDirective(self, verb, line):
    if verb == "define":
      parts = line.split(" ", 1);
      key = parts[0]
      if not self.processor.defines.has_key(key):
        if len(parts) == 2:
          value = self.processor.processDefines(parts[1])
        else:
          value = ""
        self.processor.defines[key] = value
      else:
        print "  WARNING: attempted redefinition of " + key
    elif verb == "include":
      if line.startswith('"') and line.endswith('"'):
        line = line[1:-1]
        dir = os.path.dirname(self.processor.state['file'])
        file = os.path.join(dir, line)
      else:
        raise IOError, "Invalid include declaration " + line
      if os.path.exists(file):
        self.processor.processFile(file)
      else:
        raise IOError, "Missing include file " + line
    elif verb.startswith("if"):
      control = IfControl(self.processor, verb, line)
      self.processor.pushController(control)
    else:
      Control.handleDirective(self, verb, line)
      
class IfControl(Control):
  displaying = False
  displayed = False
  closed = False

  def __init__(self, processor, verb, line):
    Control.__init__(self, processor)
    self.displaying = self.meetsCondition(verb[2:], line)
    self.displayed = self.displaying
    self.closed = False

  def meetsCondition(self, type, line):
    if type == "def":
      return self.processor.isDefined(line)
    elif type == "ndef":
      return not self.processor.isDefined(line)
    else:
      raise IOError, "Unknown if codition " + type + " " + line

  def handleDirective(self, verb, line):
    if verb == "else":
      self.displaying = not self.displayed
      self.displayed = True
    elif verb == "endif":
      self.closed = True
      self.processor.popController(self)
    elif verb.startswith("elif"):
      if self.displayed:
        self.displaying = False
      else:
        self.displaying = self.meetsCondition(verb[4:], line)
        self.displayed = self.displaying
    else:
      Control.handleDirective(self, verb, line)
    
  def handleLine(self, line):
    if self.displaying:
      Control.handleLine(self, line)

  def close(self):
    if not self.closed:
      raise IOError, "Unexpected end of if definition"

class PreProcessor:
  states = None
  output = None
  state = None
  sources = None
  resolver = None

  def __init__(self, file, resolver = None, defines = None):
    self.states = []
    if defines:
      self.defines = defines.copy()
    else:
      self.defines = {}
    self.output = open(file, "w")
    self.sources = []
    self.resolver = resolver

  def write(self, line):
    self.output.write(line)

  def pushController(self, controller):
    controller.parent = self.state['controller']
    self.state['controller'] = controller

  def popController(self, controller):
    if self.state['controller'] != controller:
      raise IOError, "Popping controller not at the top of the stack"
    self.state['controller'].close()
    self.state['controller'] = self.state['controller'].parent

  def isDefined(self, key):
    if self.defines.has_key(key):
      return True
    if (self.resolver) and (key.startswith("${")) and (key.endswith("}")):
      return self.resolver.isDefined(key[2:-1])
    return False

  def processDefines(self, line):
    changed = True
    while changed:
      changed = False
      for (key, value) in self.defines.items():
        pos = line.find(key)
        while pos >= 0:
          changed = True
          line = line[0:pos] + value + line[pos + len(key):]
          pos = line.find(key, pos)
    pos = line.find("${")
    while (pos >= 0):
      end = line.find("}", pos)
      if end >= 0:
        var = line[pos + 2:end]
        if not self.resolver:
          print "  WARNING: no resolver for " + var + " variable"
        elif self.resolver.isDefined(var):
          value = self.resolver.resolveValue(var)
          line = line[0:pos] + value + line[end + 1:]
          pos = line.find("${", pos)
          continue
        else:
          print "  WARNING: undefined variable " + var
      pos = line.find("${", pos + 1)
    return line

  def processLine(self, line):
    if line.startswith(self.state['marker']):
      line = line[len(self.state['marker']):].rstrip()
      parts = line.split(" ", 1)
      if parts[0]:
        if len(parts) == 2:
          self.state['controller'].handleDirective(parts[0], parts[1].strip())
        else:
          self.state['controller'].handleDirective(parts[0], None)
    else:
      self.state['controller'].handleLine(line)

  def processFile(self, file, marker = None):
    if not marker:
      if fnmatch.fnmatch(file, "*.css"):
        marker = "%"
      else:
        marker = "#"
    self.sources.append(file)
    fp = open(file)
    self.states.append(self.state)
    self.state = {}
    self.state['marker'] = marker
    self.state['controller'] = BaseControl(self)
    self.state['file'] = file
    pos = 0
    try:
      for line in fp:
        pos += 1
        self.processLine(line)
      fp.close()
    except:
      print "  ERROR: failure processing line", pos, "of", file
      raise
    while self.state['controller']:
      self.popController(self.state['controller'])
    self.state = self.states.pop()

  def close(self):
    self.output.close()
