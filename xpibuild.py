import os, sys, shutil, fnmatch, zipfile, preprocessor, popen2
import xml.parsers.expat, ConfigParser

def execProcess(command, args):
  cmd = []
  cmd.append("'" + command + "'")
  cmd.extend(map(lambda x: "'" + x + "'", args))
  cmd = " ".join(cmd)
  process = popen2.Popen4(cmd)
  stdout = sys.stdout
  out = process.fromchild
  while process.poll() == -1:
    line = out.readline().rstrip()
    if len(line) > 0:
      print >> stdout, line
  # read in the last lines that happened between the last -1 poll and the
  # process finishing
  for line in out:
    line = line.rstrip()
    if len(line) > 0:
      print >> stdout, line
  return process.poll()

def parseProperties(fp):
  properties = {}
  for line in fp:
    if line.startswith("#"):
      continue
    line = line.strip()
    (key, value) = line.split("=", 1)
    properties[key] = value
  return properties

class XPIBuilder(preprocessor.Resolver):
  __initialised = False
  basedir = None
  srcdir = None
  builddir = None
  bindir = None
  outputdir = None

  mozillasdk = None
  xptlink = None
  xpidl = None
  idlincludes = None

  type = None
  settings = None
  packagename = None
  buildid = None
  release = False

  def __init__(self, basedir = None):
    if basedir:
      self.basedir = os.path.abspath(os.path.realpath(basedir))
    else:
      self.basedir = os.path.abspath(os.path.realpath(os.path.dirname(os.path.dirname(__file__))))
    self.defines = {}

  def init(self):
    if (os.path.exists(os.path.join(self.basedir, "extension.properties"))):
      self.type = "extension"
    elif (os.path.exists(os.path.join(self.basedir, "application.properties"))):
      self.type = "application"
    else:
      raise Exception, "Unknown build type or missing properties"

    if not self.mozillasdk:
      if "GECKO_SDK" in os.environ.keys():
        self.mozillasdk = os.environ["GECKO_SDK"]
      else:
        self.mozillasdk = os.path.abspath(os.path.join(self.basedir, "..", "..", "gecko-sdk"))
    if not self.srcdir:
      self.srcdir = os.path.join(self.basedir, "src")
    if not self.builddir:
      self.builddir = os.path.join(self.basedir, "prebuild")
    if not self.bindir:
      self.bindir = os.path.join(self.basedir, "bin")
    if not self.outputdir:
      self.outputdir = self.basedir

    if not self.xptlink:
      self.xptlink = os.path.join(self.mozillasdk, "bin", "xpt_link")
    if not self.xpidl:
      self.xpidl = os.path.join(self.mozillasdk, "bin", "xpidl")
    if not self.idlincludes:
      self.idlincludes = [ os.path.join(self.mozillasdk, "idl"), os.path.join(self.srcdir, "components") ]

    self.settings = parseProperties(open(os.path.join(self.basedir, self.type + ".properties")))
    if self.settings.has_key('chromejar'):
      self.settings['chromebase'] = 'jar:chrome/' + self.settings['chromejar'] + '.jar!'
    else:
      self.settings['chromebase'] = 'chrome'

    if self.buildid:
      self.settings['buildid'] = self.buildid
      self.settings['fullversion'] = self.settings['version'] + "." + self.buildid
    else:
      self.settings['fullversion'] = self.settings['version']

    if not self.packagename:
      if self.release:
        self.packagename = self.settings['name'] + "-" + self.settings['fullversion'] + ".xpi"
      else:
        self.packagename = self.settings['name'] + ".xpi"

    self.__initialised = True

  def isDefined(self, key):
    if (key.startswith(self.type + ".")):
      key = key[len(self.type) + 1:]
      return self.settings.has_key(key)
    return False

  def resolveValue(self, key):
    if (key.startswith(self.type + ".")):
      key = key[len(self.type) + 1:]
      return self.settings[key]
    return ""

  def __isNewer(self, sources, target):
    if not os.path.exists(target):
      return True
    ttime = os.stat(target).st_mtime
    for source in sources:
      if not os.path.exists(source):
        return True
      stime = os.stat(source).st_mtime
      if stime > ttime:
        return True
    return False

  def __zipTree(self, zipwriter, sourcedir, path):
    for file in os.listdir(sourcedir):
      source = os.path.join(sourcedir, file)
      if os.path.isdir(source):
        self.__zipTree(zipwriter, source, path + file + "/")
      else:
        zipwriter.write(source, path + file)

  def __copyTree(self, sourcedir, targetdir):
    if not os.path.exists(targetdir):
      os.mkdir(targetdir)
    for name in os.listdir(sourcedir):
      if (fnmatch.fnmatch(name, ".*")):
        continue
      source = os.path.join(sourcedir, name)
      target = os.path.join(targetdir, name)
      if os.path.isdir(source):
        self.__copyTree(source, target)
      else:
        if not self.__isNewer([ source ], target):
          continue
        shutil.copyfile(source, target)

  def __validateXML(self, file):
    parser = xml.parsers.expat.ParserCreate()
    try:
      parser.ParseFile(open(file))
    except xml.parsers.expat.ExpatError:
      raise IOError, "XML syntax error in " + file

  def __stage(self, sourcedir = None, targetdir = None):
    if not sourcedir:
      sourcedir = self.srcdir
    if not targetdir:
      targetdir = self.builddir
    dirconfig = ConfigParser.ConfigParser()
    inifile = os.path.join(targetdir, ".buildrc")
    if os.path.exists(inifile):
      dirconfig.read(inifile)
    if not dirconfig.has_section("dependencies"):
      dirconfig.add_section("dependencies")
    newconfig = False
    if not os.path.exists(targetdir):
      os.mkdir(targetdir)
    for name in os.listdir(sourcedir):
      if (fnmatch.fnmatch(name, "*.pspimage") or      # High quality source images
          fnmatch.fnmatch(name, "*.psd") or           # High quality source images
          fnmatch.fnmatch(name, "Thumbs.db") or       # Windows crap
          fnmatch.fnmatch(name, ".*") or              # Hidden files
          fnmatch.fnmatch(name, "*~") or              # Backup files
          fnmatch.fnmatch(name, "*.inc") or           # Includes are used by the preprocessor
          fnmatch.fnmatch(name, "*.inc.*")):
        continue
      source = os.path.join(sourcedir, name)
      target = os.path.join(targetdir, name)
      if os.path.isdir(source):
        self.__stage(source, target)
      else:
        if dirconfig.has_option("dependencies", name):
          sources = dirconfig.get("dependencies", name).split(",")
        else:
          sources = [ source ]
        if not self.__isNewer(sources, target):
          continue
        if (fnmatch.fnmatch(name, "*.js") or
            fnmatch.fnmatch(name, "*.jsm") or
            fnmatch.fnmatch(name, "*.xul") or
            fnmatch.fnmatch(name, "*.xml") or
            fnmatch.fnmatch(name, "*.rdf") or
            fnmatch.fnmatch(name, "*.dtd") or
            fnmatch.fnmatch(name, "*.properties") or
            fnmatch.fnmatch(name, "*.manifest") or
            fnmatch.fnmatch(name, "*.css")):
          print "Preprocessing " + target
          try:
            processor = preprocessor.PreProcessor(target, self)
            processor.processFile(source);
          except:
            processor.close()
            os.remove(target)
            raise
          else:
            processor.close()
          if len(processor.sources) > 1:
            dirconfig.set("dependencies", name, ",".join(processor.sources))
            newconfig = True
        else:
          print "Copying " + target
          shutil.copyfile(source, target)
        if (fnmatch.fnmatch(name, "*.xul") or
            fnmatch.fnmatch(name, "*.xul") or
            fnmatch.fnmatch(name, "*.xml") or
            fnmatch.fnmatch(name, "*.rdf")):
          self.__validateXML(target)
    if newconfig:
      dirconfig.write(open(inifile, "w"))

  def __buildComponents(self):
    sourcedir = os.path.join(self.builddir, "components")
    if not os.path.exists(sourcedir):
      return
    targetdir = os.path.join(self.bindir, "components")
    if not os.path.exists(targetdir):
      os.makedirs(targetdir)

    xpidlargs = [ "-m", "typelib", "-w", "-v" ]
    for include in self.idlincludes:
      xpidlargs += [ "-I", include ]
    xpidlargs += [ "-e" ]
    xptfiles = []
    for file in os.listdir(sourcedir):
      source = os.path.join(sourcedir, file)
      if os.path.isdir(source):
        self.__copyTree(source, os.path.join(targetdir, file))
      elif fnmatch.fnmatch(file, "*.idl"):
        target = os.path.join(sourcedir, file[:-3] + "xpt")
        if target not in xptfiles:
          xptfiles += [ target ]
        if not self.__isNewer([ source ], target):
          continue
        print "Compiling " + target
        retcode = execProcess(self.xpidl, xpidlargs + [ target, source ])
        if retcode != 0:
          raise IOError, "Error compiling " + source
      elif fnmatch.fnmatch(file, "*.xpt"):
        if source not in xptfiles:
          xptfiles += [ source ]
      else:
        shutil.copyfile(source, os.path.join(targetdir, file))

    if len(xptfiles) > 0:
      if self.settings.has_key("globalxpt"):
        target = os.path.join(targetdir, self.settings['globalxpt'] + ".xpt")
        if self.__isNewer(xptfiles, target):
          print "Packaging " + target
          retcode = execProcess(self.xptlink, [ target ] + xptfiles)
          if retcode != 0:
            raise IOError, "Error creating " + target
      else:
        for file in xptfiles:
          target = os.path.join(targetdir, os.path.basename(file))
          shutil.copyfile(file, target)

  def __buildChrome(self):
    sourcedir = os.path.join(self.builddir, "chrome")
    if not os.path.exists(sourcedir):
      return
    targetdir = os.path.join(self.bindir, "chrome")
    if not os.path.exists(targetdir):
      os.makedirs(targetdir)
    if self.settings.has_key("chromejar"):
      jar = os.path.join(targetdir, self.settings['chromejar'] + ".jar")
      if os.path.exists(jar):
        os.remove(jar)
      print "Packaging " + jar
      zipwriter = zipfile.ZipFile(jar, "w", zipfile.ZIP_STORED)
      for file in os.listdir(sourcedir):
        if (fnmatch.fnmatch(file, "*.manifest") or
            fnmatch.fnmatch(file, "*.jar") or
            fnmatch.fnmatch(file, ".*")):
          continue
        source = os.path.join(sourcedir, file)
        if os.path.isdir(source):
          self.__zipTree(zipwriter, source, file + "/")
        else:
          zipwriter.write(source, file)
      zipwriter.close()
    else:
      self.__copyTree(sourcedir, targetdir)

  def build(self):
    if not self.__initialised:
      self.init()

    self.__stage()
    self.__buildComponents()
    self.__buildChrome()

    if not os.path.exists(self.bindir):
      os.makedirs(self.bindir)

    for file in os.listdir(self.builddir):
      if ((file == "components") or (file == "chrome") or
          fnmatch.fnmatch(file, ".*")):
        continue
      source = os.path.join(self.builddir, file)
      target = os.path.join(self.bindir, file)
      if os.path.isdir(source):
        self.__copyTree(source, target)
      elif self.__isNewer([ source ], target):
        shutil.copyfile(source, target)

  def package(self):
    if not self.__initialised:
      self.init()
    if not os.path.exists(self.bindir):
      self.build()
    package = os.path.join(self.outputdir, self.packagename)
    if os.path.exists(package):
      os.remove(package)
    print "Packaging " + package
    zipwriter = zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED)
    self.__zipTree(zipwriter, self.bindir, "")
    zipwriter.close()

  def clean(self):
    if not self.__initialised:
      self.init()
    if (os.path.exists(self.builddir)):
      shutil.rmtree(self.builddir)
    if (os.path.exists(self.bindir)):
      shutil.rmtree(self.bindir)
    package = os.path.join(self.outputdir, self.packagename)
    if (os.path.exists(package)):
      os.remove(package)

def main():
  from optparse import OptionParser
  parser = OptionParser()
  parser.add_option("-r", "--release", action="store_true", dest = "release", default = False,
                    help="configure build for a release")
  parser.add_option("-b", "--buildid", dest = "buildid", default = False,
                    help="set a build identifier for the build")
  (options, args) = parser.parse_args()
  builder = XPIBuilder()
  builder.release = options.release
  builder.buildid = options.buildid
  
  if len(args) == 0:
    builder.build()
  else:
    for action in args:
      if action in ["clean", "build", "package"]:
        method = getattr(builder, action)
        method()

if __name__ == "__main__":
  main()
