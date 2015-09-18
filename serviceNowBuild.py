'''
Copyright (c) 2013 Fruition Partners, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

Modifications by John Andersen (http://www.john-james-andersen.com)
- Support for Sublime Text 3
- Migrated to JSONv2 support instead of JSON plugin support
- Enhanced conflict checking - when saving a file, we first check to 
  make sure that the server version is not in conflict with the initial local
  version
'''

import sublime
import sublime_plugin
#import urllib.request as urllib2
try:
        # For Python 3.0 and later
        import urllib.request as urllib2
except ImportError:
        # Fall back to Python 2's urllib2
        import urllib2 as urllib2
import re
import base64
import json
import hashlib
import sys
import os
import traceback

class ServiceNowBuildListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        view.run_command('service_now_build')

    def on_load(self,view):
        sublime.set_timeout(syncFileCallback,15)
        

class ServiceNowBuildCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        # Get the body of the file
        reg = sublime.Region(0, self.view.size())
        #print "View: "+self.view.substr(reg)
        
        self.text = self.view.substr(reg)

        # Get the Base64 encoded Auth String
        authentication = get_authentication(self, edit)
        if not authentication:
            return

        # Get the field name from the comment in the file
        fieldname = get_fieldname(self.text)           

        try:
            return self.postByJsonV2(authentication)
        except urllib2.HTTPError as e:
            err = 'SN-Sublime - HTTP Error: %s' % (str(e.code))
        except ValueError as ve:
            #try:
            #    return self.postByJsonV2(authentication)
            #except (urllib2.URLError) as (e):
                #err = 'SN-Sublime - URL Error: %s' % (str(e))
            err = 'SN-Sublime - Value Error: %s' % (str(e))
        #except (urllib2.URLError) as (e):
        #    #Try again in case instance is using Dublin or later with JSONv2. Url is different
        #    try:
        #        return self.postByJsonV2(authentication)
        #    except (urllib2.URLError) as (e):
        #        err = 'SN-Sublime - URL Error: %s' % (str(e))
        except:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
            err = "Unknown Error: "+str(sys.exc_info()[1])
        sublime.error_message(err)
        traceback.print_tb(exc_tb)
        print (err)


        return

    def postByJson(self, authentication):
        fieldname = get_fieldname(self.text) 
        data = json.dumps({fieldname: self.text})          
        url = self.url + "&sysparm_action=update&JSON"
        url = url.replace("sys_id", "sysparm_query=sys_id")
        result = http_call(authentication, url, data)
        print ("SN-Sublime - File Successully Uploaded via JSON Plugin")
        return

    def postByJsonV2(self, authentication):
        fieldname = get_fieldname(self.text)
        settings = sublime.load_settings('SN.sublime-settings')
        urlHash = str(hashlib.sha224(self.url.replace("\r","").encode('utf-8')).hexdigest())
        localHash = settings.get(urlHash)
        url = self.url
        url = url.replace("sys_id", "sysparm_query=sys_id")
        url = url + "&JSONv2"
        
        if not localHash:
            print ("No previous local copy exists...saving our script to the server")
        else:
            print ("Previous local copy exists...checking to see if it conflicts with server version")
            result = http_call_get(authentication, url)
            resultObj = json.loads(result.decode('utf-8'))
            serverData = resultObj['records'][0][str(fieldname)]
            #serverData = serverData.replace("\r","")
            #print ("SERVER DATA\n\n:"+serverData)
            serverHash = str(hashlib.sha224(serverData.replace("\r","").encode('utf-8')).hexdigest())
            newLocalHash = str(hashlib.sha224(self.text.replace("\r","").encode('utf-8')).hexdigest())

            if serverHash != localHash and serverHash != newLocalHash:
                print ("Hash Mismatch Local: "+localHash+" Server: "+serverHash + " NewLocalHash: " + newLocalHash)
                #sublime.error_message("ERROR: This file is out of sync with the instance.  This save action will not be committed.\n\nPlease reconcile the differences.")
                if sublime.ok_cancel_dialog("ERROR: This file is out of sync with the instance.\n\nPress OK to still push your version to the server.\nPress Cancel to stop the save so that you can resolve the issue.\n\nPlease Note: pressing OK will over-write the server copy"):
                    print("Out of sync version will be pushed up to the server.  Server version will be over written.")
                else:
                    print("No save action will take place") 
                    return
            else:
                print ("Comparison to the server looks good.  No differences.")



        newTextHash = str(hashlib.sha224(self.text.replace("\r","").encode('utf-8')).hexdigest())
        fieldname = get_fieldname(self.text) 
        data = json.dumps({fieldname: self.text})            
        url = self.url + "&sysparm_action=update&JSONv2"
        url = url.replace("sys_id", "sysparm_query=sys_id")
        result = http_call(authentication, url, data)
        print ("File Successully Uploaded to SN via JSONv2")

        settings.set(urlHash, newTextHash)
        settings = sublime.save_settings('SN.sublime-settings')
        return
        

class ServiceNowSync(sublime_plugin.TextCommand):
    def run(self, edit):
        # Get the body of the file
        reg = sublime.Region(0, self.view.size())
        self.text = self.view.substr(reg)

        # Get the Base64 encoded Auth String
        authentication = get_authentication(self, edit)
        if not authentication:
           return

        try:
            url = self.url + "&sysparm_action=get&JSONv2"
            url = url.replace("sys_id", "sysparm_sys_id")
            print ("Trying to sync with existing file: "+url)
            fieldname = get_fieldname(self.text) 
            response_data = json.loads(http_call(authentication,url,'').decode('utf-8'))
            dataz = response_data['records'][0]
            serverText = response_data['records'][0][fieldname].replace("\r","")
            
            if self.text != serverText and sublime.ok_cancel_dialog("File has been updated on server. \nPress OK to Reload."):
                self.view.erase(edit, reg)
                self.view.insert(edit,0,serverText)
            else:
                print ("Comparison to the server looks good.  No differences.")
            return
        except urllib2.HTTPError as e:
            err = 'SN-Sublime - HTTP Error %s' % (str(e.code))
        except urllib2.URLError as e:
            err = 'SN-Sublime - URL Error %s' % (str(e.code))
        print (err)
        

def http_call(authentication, url, data):
    print("http_call")
    data =  data.encode('utf-8') 
    timeout = 15
    request = urllib2.Request(url, data)
    request.add_header("Authorization", authentication)
    request.add_header("Content-type", "application/json")
    http_file = urllib2.urlopen(request, timeout=timeout)
    statusCode = http_file.getcode()
    #print "Status Code: "+str(http_file.getcode())
    result = http_file.read()
    #print result
    #json.loads(result)


    return result

def http_call_get(authentication, url):
    print("http_call_get")
    timeout = 15
    request = urllib2.Request(url)
    request.add_header("Authorization", authentication)
    request.add_header("Content-type", "application/json")
    http_file = urllib2.urlopen(request, timeout=timeout)
    statusCode = http_file.getcode()
    #print "Status Code: "+str(http_file.getcode())
    result = http_file.read()
    #print "RESULT: " + result
    #json.loads(result)


    return result
    

def get_authentication(sublimeClass, edit):
    # Get the file URL from the comment in the file
    sublimeClass.url = get_url(sublimeClass.text)
    if not sublimeClass.url:
        return False

    # Get the instance name from the URL
    instance = get_instance(sublimeClass.url)
    if not instance:
        return False

    settings = sublime.load_settings('SN.sublime-settings')
    reg = sublime.Region(0, sublimeClass.view.size())
    text = sublimeClass.view.substr(reg)

    authMatch = re.search(r"__authentication[\W=]*([a-zA-Z0-9:~`\/\!@#$%\^&*()_\-;,.]*)", text)

    if authMatch and authMatch.groups()[0] != "STORED":
        user_pass = authMatch.groups()[0]
        authentication = store_authentication(sublimeClass, edit, user_pass, instance)
    else:
        authentication = settings.get(instance)

    if authentication:
        return "Basic " + authentication
    else:
        sublime.error_message("SN-Sublime - Auth Error. No authentication header tag found")   
        return False


def store_authentication(sublimeClass, edit, authentication, instance):
    base64string = base64.b64encode(authentication.encode('utf-8')).decode('utf-8').replace('\n', '')
    reg = sublime.Region(0, sublimeClass.view.size())
    text = sublimeClass.view.substr(reg)
    sublimeClass.text = text.replace(authentication, "STORED")
    sublimeClass.view.replace(edit, reg, sublimeClass.text)

    settings = sublime.load_settings('SN.sublime-settings')
    settings.set(instance, base64string)
    settings = sublime.save_settings('SN.sublime-settings')

    return base64string

def get_fieldname(text):
    fieldname_match = re.search(r"__fieldName[\W=]*([a-zA-Z0-9_]*)", text)
    if fieldname_match:
        return fieldname_match.groups()[0]
    else:
        return 'script'

def get_url(text):
    url_match = re.search(r"__fileURL[\W=]*([a-zA-Z0-9:/.\-_?&=]*)", text)

    if url_match:
        return url_match.groups()[0]
    else:
        print ("SN-Sublime - Error. Not a ServiceNow File")
        return False


def get_instance(url):
    instance_match = re.search(r"//([a-zA-Z0-9]*)\.", url)
    if instance_match:
        return instance_match.groups()[0]
    else:
        print ("SN-Sublime - Error. No instance info found")        
        return False


def syncFileCallback():
    sublime.active_window().active_view().run_command('service_now_sync')

