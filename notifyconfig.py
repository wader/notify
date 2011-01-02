# $Id: notifyconfig.py 1017 2007-01-23 23:42:48Z mattias $
#
# Config parsing and evaluation


import shlex
import re
import os


# like os.path.abspath but with argument for current path
def abspath(path, current_path):
    if os.path.isabs(path):
        s = path
    else:
        s = os.path.normpath(current_path + os.path.sep + path)

    return os.path.normpath(s)


class NotifyConfigSectionAttribute:
    def __init__(self, line, value):
        self.line = line
        self.value = value

    def config(self):
        c = "# line %d" % self.line
        c += "\t%s"

class NotifyConfigSection:
    def __init__(self, line, name):
        self.line = line
        self.name = name
        self.re = None
        self.is_file = False
        self.is_dir = False
        self.attributes = {}
    
        for delegate in ["__getitem__", "__setitem__", "keys", "has_key",
                "items"]:
            setattr(self, delegate, getattr(self.attributes, delegate))

    def config(self):
        c = ""
        for attr in self.attributes:
            c += "# line %d\n" % attr.line
            c += "%s:\n" % attr.name
            if type(attr) is list:
                for a in attr:
                    c += a.config()
            else:
                c += attr.config()

        return c

class NotifyConfigError(Exception):
    def __init__(self, config, text, line):
        self.config = config
        if line == None:
            self.line = config.line_number
        else:
            self.line = line
        self.text = text

    def __str__(self):
        return "%s:%d: %s" % \
                (os.path.basename(self.config.config_path), \
                self.line, self.text)

class NotifyConfig:
    defaults = {
            "config": {
                # "path" is set in __init__
                "foreground": "False",
                "debug": "0",
                "stdout": "/dev/null",
                "stderr": "/dev/null",
                "subprocess_limit": "10",
                "subprocess_poll_interval": "1",
                "subprocess_stdout": "/dev/null",
                "subprocess_stderr": "/dev/null",
                "move_event_timeout": "0.5"
                },
            "default": {},
            "env": {}
            }

    def __init__(self, config_path, base_path):
        self.config_path = config_path
        self.real_sections = None

        self.defaults["config"]["path"] = base_path

    # for self.config["section"]["value"]
    def __getitem__(self, item):
        return self.real_sections[item]

    # use self as iterator class
    def __iter__(self):
        self.iter = 0
        return self

    def next(self):
        try:
            self.iter += 1
            return self.real_sections[self.real_sections_order[self.iter - 1]]
        except IndexError:
            raise StopIteration

    def add_section(self, name):
        if self.sections.has_key(name):
            self.error("section '%s' already defined at line %d" % \
                    (name, self.sections[name].line))
        sect = NotifyConfigSection(self.line_number, name)
        self.sections[name] = sect
        self.current_section = sect
        self.sections_order.append(name)

    def add_attribute(self, key, value, multi=False):
        attr = NotifyConfigSectionAttribute(self.line_number, value)
        
        if self.current_section.attributes.has_key(key):
            if multi:
                self.current_section.attributes[key].append(attr)
            else:
                self.error("attribute '%s' already set at line %d " % \
                        (key, self.current_section.attributes[key].line))
        else:
            if multi:
                attr = [attr]
            self.current_section.attributes[key] = attr

    def error(self, text, line=None):
        raise NotifyConfigError(self, text, line)

    def read(self, override={}, callback=None):
        old = self.real_sections
        try:
            self.read_parse()
            # add defaults if not found in file
            self.read_defaults()
            self.read_eval(old, override)
        except NotifyConfigError:
            raise
        else:
            self.real_sections = self.sections
            self.real_sections_order = self.sections_order
            del(self.sections)
            del(self.sections_order)
            
            if callback != None:
                callback.reload(old, self.real_sections)
            
            if old != None:
                self.read_cleanup(old)
    
    def read_cleanup(self, old_sections):
        # close file attributes in old config
        for attr in ["stdout", "stderr", "subprocess_stdout", \
		"subprocess_stderr"]:
            
            # skip if running in foreground
            if old_sections["config"]["foreground"].value and \
                    attr in ("stderr", "stdout"):
                continue

            old_sections["config"][attr].file.close()
    
    def read_defaults(self):
        for sect, attr in self.defaults.items():
            if not self.sections.has_key(sect):
                self.add_section(sect)

            for attrname, attrvalue in attr.items():
                if not self.sections[sect].has_key(attrname):
                    self.sections[sect][attrname] = \
                            NotifyConfigSectionAttribute(0, attrvalue)

    def read_parse(self):
        self.sections = {}
        self.sections_order = []
        self.current_section = False
        self.line_number = 0

        lines = open(self.config_path, "r").readlines()
        lines.append(" ") 

        # skip comments and combinse escaped lines
        def gen_lines(lines):
            line_number = 0
            line_number_delta = 0
            line_acc = ""

            # add empty string if last line is escaped
            for line in lines + [""]:

                line = line.strip("\n")

                if len(line) > 0:
                    s = line.strip()
                    if len(s) > 0 and s[0] == "#":
                        line_number += 1
                        continue
                    elif line[-1] == "\\":
                        line_acc += line[:-1]
                        line_number_delta += 1
                        continue
                    else:
                        line_acc += line
                        line_number += 1
                else:
                    line_number += 1

                if len(line_acc) > 0:
                    yield (line_number, line_acc)
                
                line_acc = ""
                line_number += line_number_delta
                line_number_delta = 0

        for self.line_number, line in gen_lines(lines):
            indent = len(line) > 0 and line[0] in (" ", "\t")
            line = line.strip()

            if line == "":
                continue
            
            if line[-1] == ":":
                self.add_section(line[:-1])
                continue

            if not indent:
                self.error(
                        "non indented attribute or invalid section name '%s'" \
                                % line)
                        
            if self.current_section.name == "watch":
                self.add_attribute(line, "")
            elif self.current_section.name in ("env", "config"):
                parts = line.split(" ", 1)
		# if only one value, dummy add a empty string
		if len(parts) == 1:
		    parts.append("")
                self.add_attribute(parts[0], parts[1])
            else:
                try:
                    parts = shlex.split(line)
                except ValueError, e:
                    self.error("invalid syntax, %s: %s" % (e, line))
                # TODO: multi...
                self.add_attribute(parts[0], parts[1:], multi=False)
        
    def read_eval(self, old, override):
        for defsect, defattr in self.defaults.items():
            if not self.sections.has_key(defsect):
                continue

            for name, attr in self.sections[defsect].items():
                if name not in defattr.keys():
                    self.error("unknown option '%s' in %s section" % \
                            (name, defsect), attr.line)

	for attr, value in override.items():
	    self.sections["config"][attr].value = value

        actions = ("add", "delete", "move", "open", "close_nowrite", \
                "close_write", "event", "stop")


        d = self.sections["default"]
        for name, s in self.sections.items():
            if name in ("watch", "default", "env", "config"):
                continue
            for key, a in d.attributes.items():
                if not s.attributes.has_key(key):
                    s.attributes[key] = a

        for name, s in self.sections.items():
            if name in ("watch", "default", "env", "config"):
                continue

            l = name.rsplit("/", 1)
            if len(l) != 2 or l[0][0] != "/":
                self.error( \
                        "invalid regexp section '%s' should be " \
                        "'/regexp/[options]:'" % name,
                        s.line)

            regexp = l[0][1:]
            reflags = 0
            flags = l[1]
            if "i" in flags: reflags |= re.I
            if "d" in flags: s.is_dir = True
            if "f" in flags: s.is_file = True
            for f in ["i", "d", "f"]:
                flags = flags.replace(f, "")
            if flags != "":
                self.error("unknown match rule option '%s'" % flags, s.line)

            try:
                s.re = re.compile(regexp, reflags)
            except re.error, e:
                self.error("%s: %s" % (name, e), s.line)

        for name, s in self.sections.items():
            for key, a in s.attributes.items():
                if name not in ("watch", "env", "config") and \
                    key not in actions:
                    self.error( \
                            "unknown action '%s' should be " % key + \
                            ", ".join(actions[:-1]) + ", or " + actions[-1],
                            a.line)
        
	# bool attributes
	for attr in ("foreground",):
            sect = self.sections["config"]
	    
	    # not allow to change in runtime
	    if old != None and attr in ("foreground",):
		sect[attr].value = old["config"][attr].value
		continue

	    if sect[attr].value.lower() == "true":
		sect[attr].value = True
	    elif sect[attr].value.lower() == "false":
		sect[attr].value = False
	    else:
		self.error( \
			"invalid bool value '%s' for %s should be " \
			"true or false" % (sect[attr].value, sect[attr].line))

        # int attributes
        for attr in ("debug", "subprocess_limit"):
            sect = self.sections["config"]
            try:
                sect[attr].value = int(sect[attr].value)
            except ValueError:
                self.error("invalid value '%s' for %s should be an integer" \
                        % (sect[attr].value, attr),
                        sect[attr].line)
        
        # float attributes
        for attr in ("move_event_timeout", "subprocess_poll_interval"):
            sect = self.sections["config"]
            try:
                sect[attr].value = float(sect[attr].value)
            except ValueError:
                self.error("invalid value '%s' for %s should be a number" \
                        % (sect[attr].value, attr),
                        sect[attr].line)

        # file attributes, note that .file is set
        for attr in ("stdout", "stderr", "subprocess_stdout", \
		"subprocess_stderr"):

            # skip not first reconf and is running in foreground
            if old != None and \
                    self.sections["config"]["foreground"].value and \
                    attr in ("stderr", "stdout"):
                continue

            sect = self.sections["config"]
	    try:
                path = abspath(sect[attr].value, \
                        self.sections["config"]["path"].value)
                sect[attr].file = open(path, "a")
            except IOError, e:
                self.error("open failed for %s: %s" % (attr, e),
                        sect[attr].line)

    def dump(self):
        conf = ""
        for name in self.real_sections_order:
            s = self.real_sections[name]
            conf += "# from line %d\n" % s.line
            conf += "%s:\n" % s.name
            for key, a in s.attributes.items():
                
                if name == "watch":
                    conf += "  # from line %d\n" % a.line
                    conf += "  %s\n" % key
                elif name in ("env", "config"):
                    conf += "  # from line %d\n" % a.line
                    conf += "  %s %s\n" % (key, a.value)
                else:
                    for attr in a:
                        conf += "  # from line %d\n" % attr.line
                        conf += "  %s %s\n" % (key, \
                                " ".join(['"%s"' % v for v in attr.value]))

        return conf

