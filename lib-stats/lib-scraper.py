# Given a set of apps under a certain category,
# this scrapes them for all imported libraries and
# sanitizes the result to obtain a list of all
# imported third-party libraries (a first-party library is a module
# that is part of the app that is imported)

import os
import sys
import copy

from collections import OrderedDict
import json

from util import write_map, read_map, remove_dups, write_list
from pyflakes import reporter as modReporter
from pyflakes.api import checkRecursive

def group_by_app(a, apps, src, ungrouped, target, target2=None):
    print("Grouping all "+target+" by app")
    libs = remove_dups(ungrouped)
    if a.endswith(".py"):
        # single-module apps don't have first-party imports
        if target2:
            apps[a][target2] = libs
        else:
            apps[a][target] = libs
    else:
        if apps[a].get(target) == None:
            apps[a][target] = OrderedDict()
        apps[a][target][src] = libs

def get_prefix(path):
    dirs = path.split('/')
    script_idx = len(dirs)
    prefix = "/".join(dirs[0:script_idx-1])
    return prefix

def get_supermod(name):
     if name.count('.') >= 1:
        mod = name.split('.')
        return "/"+mod[0]
     else:
         return ""

# we only want to store the top-level package
def get_pkg_names(app, target):
    print("Extracting package names for "+target)
    pkgs = []
    for lib in app[target]:
        tlp = get_supermod(lib)
        if tlp == "" or lib == "RPi.GPIO":
            # let's make an exception for RPi.GPIO -- that's the pkg name
            tlp = lib
        else:
            tlp = tlp.lstrip("/")
        pkgs.append(tlp)
    return remove_dups(pkgs)

def make_super_mod_name(prefix, name):
    supermod =  prefix+get_supermod(name)+".py"

    # this case is true if the module doesn't have a supermodule
    if supermod == prefix+".py":
        return ""

    return supermod

def make_mod_name(prefix, name):
    if name.count('.') >= 1:
        mod = name.split('.')
        return prefix+"/"+mod[0]+"/"+mod[1]+".py"

    return prefix+"/"+name+".py"

def replace_fp_mod(prefix, mod, d, visited):
    n = make_mod_name(prefix, mod)
    s = make_super_mod_name(prefix, mod)
    #print("Looking at "+n+" and "+s)
    if d.get(n) == None and d.get(s) == None:
        return [mod]
    else:
        insuper = False
        if d.get(n) != None:
            mo = n
        elif d.get(s) != None:
            insuper = True
            mo = s

        if mo in visited:
            print(mo+" is imported recursively, so don't go deeper")
            return []
        else:
            visited.append(mo)
            l = []
            for m in d[mo]:
                next_mod = prefix+get_supermod(mod)
                if insuper:
                    next_mod = prefix

                tmp = replace_fp_mod(next_mod, m, d, visited)
                l.extend(tmp)
            return l

def replace_fp_mod_app(app, target):
    print("Replacing the first-party imports for group: "+target)
    libs = []
    for src, i in app[target].items():
        pref = get_prefix(src)
        for l in i:
            try:
                # add entry for each src once we've tried to replace it
                recurs_limit = []
                tmp = replace_fp_mod(pref, l, app['raw_imports'], recurs_limit)

                # this is just to avoid printing redundant messages
                if not(len(tmp) == 1 and tmp[0] == l):
                    print("replacing "+l+" with "+str(tmp))
                libs.extend(tmp)
            except RecursionError:
                print("died trying to replace "+l+" in "+src)
                sys.exit(-1)
    return remove_dups(libs)

def call_native_proc(l):
    if "os.system" in l or "os.spawnlp" in l or "os.popen" in l or "subprocess.call" in l or "subprocess.Popen" in l:
        return True
    return False

def scan_source(src):
    f = open(src, "r")
    lines = f.readlines()
    f.close()
    # these are the calls to native code that we've observed
    for l in lines:
        clean = l.strip()
        if not clean.startswith("#") and call_native_proc(clean):
            print("Found call to native proc in code: "+clean)
            return True
    return False

# pass in the category: visual, audio or env
cat = sys.argv[1]

# expect apps to be located in apps/cat/
app_path = "apps/"+cat+"/"

f = open(cat+"-pyflakes-py3-report.txt", "w+")
reporter = modReporter.Reporter(f, f)
num, imps, un = checkRecursive([app_path], reporter)
f.close()

# the modules in this list are likely written in python2 so run pyflakes
# on python2
os.system("python2 -m pyflakes "+app_path+" > "+cat+"-pyflakes-py2-report.txt")

# let's organize our imports by app
app_list = os.listdir(app_path)

apps = OrderedDict()
for a in app_list:
    if not a.startswith('.'):
        app = app_path+a
        apps[app] = OrderedDict()

# now, let's parse the imports and unused, and organize them by app
imps_2 = read_map(cat+"-flakes-imports-py2.txt")
un_2 = read_map(cat+"-flakes-unused-py2.txt")

# the py2 run of flakes probably finds imports found by the py3 run
# let's merge the two dicts
# see: https://stackoverflow.com/questions/38987/how-to-merge-two-python-dictionaries-in-a-single-expression#26853961
imports_raw = {**imps, **imps_2}
unused_raw = {**un, **un_2}

#write_map(imports_raw, cat+"-flakes-imports.txt")
#write_map(unused_raw, cat+"-flakes-unused.txt")

os.remove(cat+"-flakes-imports-py2.txt")
os.remove(cat+"-flakes-unused-py2.txt")

print("Number of "+cat+" apps being scraped: "+str(len(apps)))

call_to_native = OrderedDict()
hybrid = OrderedDict()
# iterate through all apps to organize the imports
for a in apps:
    print("--- current app: "+a)
    proc_srcs = []
    hybrid_srcs = []
    for src, i in imports_raw.items():
        if a in src:
            print(" *** "+src)
            # want raw_imports AND imports since raw_imports is used
            # in the unused parsing as well
            group_by_app(a, apps, src, i, 'raw_imports', 'imports')

            # iterate over the raw_imports to collect the ones that call native code/use ctypes
            print("Collecting apps that call a native process or are hybrid python-C")
            for l in i:
                if l == "subprocess.call" or l == "subprocess.Popen":
                    print("Call to native proc")
                    proc_srcs.append(src)
                elif l == "os" or l == "subprocess":
                    if scan_source(src):
                        proc_srcs.append(src)
                elif l == "ctypes":
                    print("Use ctypes")
                    hybrid_srcs.append(src)

            # iterate over the raw_imports to collect the ones that are hybrid
            print("Collecting apps that are hybrid python-C")

    if len(proc_srcs) > 0:
        call_to_native[a] = remove_dups(proc_srcs)

    if len(hybrid_srcs) > 0:
        hybrid[a] = remove_dupes(hybrid_srcs)

    # iterate over each source file's imports to find
    # the first-party imports
    if not a.endswith(".py"):
        # make sure to sort the sources to have a deterministic analysis
        apps[a]['raw_imports'] = OrderedDict(sorted(apps[a]['raw_imports'].items(), key=lambda t: t[0]))

        apps[a]['imports'] = replace_fp_mod_app(apps[a], 'raw_imports')

    # we only want to store the pkg names
    apps[a]['imports'] = get_pkg_names(apps[a], 'imports')

    # remove all __init__.py unused imports since they aren't actually unused
    for src, i in unused_raw.items():
        if a in src and not src.endswith("__init__.py"):
            print(" *** "+src)
            group_by_app(a, apps, src, i, 'unused')

    # iterate of each source's files imports to remove unused imports that actually appear
    # in the list of imports
    if not a.endswith(".py"):
        # make sure to sort the sources to have a deterministic analysis
        apps[a]['unused'] = OrderedDict(sorted(apps[a]['unused'].items(), key=lambda t: t[0]))

        apps[a]['unused'] = replace_fp_mod_app(apps[a], 'unused')

        # remove the raw imports once we're done with all the parsing
        del apps[a]['raw_imports']

    # now we only want to store the pkg names
    apps[a]['unused'] = get_pkg_names(apps[a], 'unused')

    # if a pkg is under unused (possibly bc an app submodule doesn't
    # use it or some submodule is unused), but it also appears in imports
    # consider it used by the app, so remove it from unused
    pruned_unused = []
    for l in apps[a]['unused']:
        if not l in apps[a]['imports']:
            pruned_unused.append(l)

    apps[a]['unused'] = pruned_unused

    # let's get rid of all the empty unused lists
    if len(apps[a]['unused']) == 0:
        del apps[a]['unused']

write_map(call_to_native, cat+"-call-native.txt")
write_map(hybrid, cat+"-hybrid-apps.txt")
write_map(apps, cat+"-app-imports.txt")
