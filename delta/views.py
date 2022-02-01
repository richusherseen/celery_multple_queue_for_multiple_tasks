import json
import os
import sys
import time
import traceback
from django.http import JsonResponse
import requests
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from requests_oauthlib import OAuth2Session
from delta.models import RunmybotSetting
from urllib.parse import urlparse
from urllib.parse import parse_qs
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from celery import shared_task

@method_decorator(csrf_exempt, name='dispatch')
class Delta(View):
    def __init__(self) -> None:
       
        self.root_dir = os.path.abspath(os.curdir)
    
    def post(self, request):
        parameter = RunmybotSetting.objects.get(
            conf_key='aon_parameters').conf_value
        parameter = json.loads(parameter)
        get_data.apply_async((parameter,), queue="test")
        return JsonResponse({'status':True, 'msg': 'mail reading and procssing started'})
    


@shared_task
def process(parameter, jsondata):
    try:
        token_object = RunmybotSetting.objects.get(
            conf_key='aon_outlook_token')
        token = eval(token_object.conf_value)
        now = time.time()
        if now >= token['expires_at']:
            print('-------token expired----')
            token = refresh_token(token_object)
            
            # token = eval(obj.token)
        access_token = token['access_token']
        # jsondata = get_data.apply_async((parameter,), queue="test")
        
        
        rslt = []
        next_link = True
        count = 0
        
        value = jsondata['value']
        print("value--",len(value))
    
        for p in value:
            count+=1
            print("count--",count)
            if '@removed' in p:
                print('---- removed ---')
                continue
            message_id = p['id']
            sender = p['sender']['emailAddress']['address']
            print('-- subject --',p['subject'])
            # if mail subject didnt contain 'ID#' skip that mail
            if p['subject'].find('ID#') < 0:
                if sender.lower().startswith("microsoft"):
                    print('--avoiding mails from microsoft---')
                    continue
                elif sender == parameter['shared_mail_id']:
                    print(f"--avoiding mails from {parameter['shared_mail_id']} ---")
                    continue
                else:
                    print('----- doing mail operation ------')
                    sent_mail_dict = parameter['no_transid_mail_format'][0]
                    sent_mail_dict['to_recipient'] = sender
                    sent_mail_dict['message_id'] = message_id
                    print("no id-",sent_mail_dict)
                    st = send_mail(sent_mail_dict, parameter, access_token)
                    rslt.append(st)
                    res = {"status": False}
                    emailMove(message_id, res, parameter, access_token)
                    continue
            if p['hasAttachments'] == True:
                print("---- sleep for 3 min ----")
                time.sleep(60)
                res = {"status": True}
                c = emailMove(message_id, res, parameter, access_token)
                print('-- attachemt result --',c)
            else:
                res = {"status": False}
                c = emailMove(message_id, res, parameter, access_token)

        
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        print({'Exception': str(e),
                "Line number" : str(exc_tb.tb_lineno)})
        
        return JsonResponse({'Exception': str(e),
                "Line number" : str(exc_tb.tb_lineno)})


def refresh_token(token_object):
    token = eval(token_object.conf_value)
    aad_auth = OAuth2Session(
        str(RunmybotSetting.objects.get(
            conf_key='aon_app_id').conf_value),
        token=token,
        scope=" ".join(token["scope"]),
        # redirect_uri=settings['redirect']
    )
    tenant_id = str(RunmybotSetting.objects.get(
        conf_key='aon_tenant_id').conf_value)
    print('tenant-', tenant_id)
    refresh_params = {
        'client_id': str(RunmybotSetting.objects.get(conf_key='aon_app_id').conf_value),
        'client_secret': str(RunmybotSetting.objects.get(conf_key='aon_app_secret').conf_value),
    }

    new_token = aad_auth.refresh_token(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token", **refresh_params)
    token_object.conf_value = str(new_token)
    token_object.save()
    return eval(token_object.conf_value) 

@shared_task
def get_data(parameter):
    try:
        token_object = RunmybotSetting.objects.get(
            conf_key='aon_outlook_token')
        token = eval(token_object.conf_value)
        
        now = time.time()
        if now >= token['expires_at']:
            print('-------token expired----')
            token = refresh_token(token_object)
        delta_token = RunmybotSetting.objects.get(
            conf_key=parameter['shared_mail_id'])
        
        
        endpoint = f"https://graph.microsoft.com/v1.0/users/{parameter['shared_mail_id']}/mailFolders/Inbox/messages/delta"  
        # print("endpoint--",endpoint)

        
        headers = {"Authorization": token['access_token'],
                    'Prefer': 'outlook.body-content-type="text"'}
        if not len(delta_token.conf_value):
            print('----- calling without delta link -----')
            response = requests.get(endpoint, headers=headers).json()
            jsondata = json.dumps(response)
            jsondata = json.loads(jsondata)
            process.delay(parameter, jsondata)
            
        else:
            print('----- calling with delta link -----')
            params = { "$deltatoken" : delta_token.conf_value }
            response = requests.get(endpoint, headers=headers, params=params).json() 
            jsondata = json.dumps(response)
            jsondata = json.loads(jsondata)
            process.delay(parameter, jsondata)
        
        if "@odata.nextLink" in jsondata:
            print('----- nextlink found -----')
            nextLink = jsondata['@odata.nextLink']
            parsed_url = urlparse(nextLink)
            skiptoken = parse_qs(parsed_url.query)['$skiptoken'][0]
            # print("skiptoken--",skiptoken)
            params = { "$skiptoken" : skiptoken }
            response = requests.get(endpoint, headers=headers, params=params).json()
            
            if 'error' in response:
                if response['error']['code'] == "InvalidAuthenticationToken":
                    print('--- token expired while processing next link ---')
                    token = refresh_token(token_object)
                    headers = {"Authorization": token['access_token'],
                    'Prefer': 'outlook.body-content-type="text"'}
                    response = requests.get(endpoint, headers=headers, params=params).json()
                else:
                    raise Exception(response)

            jsondata = json.dumps(response)
            jsondata = json.loads(jsondata)
            process.delay(parameter, jsondata)
        
        if "@odata.deltaLink" in jsondata:
            print('----- deltalink found -----')
            delta_link = jsondata['@odata.deltaLink']
            
            parsed_url = urlparse(delta_link)
            deltatoken = parse_qs(parsed_url.query)['$deltatoken'][0]
            delta_token.conf_value = deltatoken
            print("deltatoken--",deltatoken)
            delta_token.save()
    
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        print({'Exception': str(e),
                "Line number" : str(exc_tb.tb_lineno)})


        

def emailMove( message_id, result, parameter, access_token):
        try:
            # print("result--", result)
            if result['status']:
                print("Moving file to success folder")
                if parameter['shared_mail_box']:
                    folder = RunmybotSetting.objects.get(
                        conf_key='aon_success_folder_shared').conf_value
                else:
                    folder = RunmybotSetting.objects.get(
                        conf_key='aon_success_folder').conf_value
            else:
                print("Moving file to failed folder")
                if parameter['shared_mail_box']:
                    folder = RunmybotSetting.objects.get(
                        conf_key='aon_failed_folder_shared').conf_value
                else:
                    folder = RunmybotSetting.objects.get(
                    conf_key='aon_failed_folder').conf_value
            
            if parameter['shared_mail_box']:
                url = f"https://graph.microsoft.com/v1.0/users/{parameter['shared_mail_id']}/messages/{message_id}/move"
            else:
                url = "https://graph.microsoft.com/v1.0/me/messages/"+message_id+"/move"
            payload = "{\n  \"destinationId\": \"" + folder + "\"\n}"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': access_token,
            }
            response = requests.request(
                "POST", url, headers=headers, data=payload)
            print(response.status_code)
            if response.status_code == 201:
                datas = json.loads(response.text)

                return {"status": True}
            else:
                raise Exception(json.loads(response.text))
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print({'Exception': str(e),
                    "Line number" : str(exc_tb.tb_lineno)})
            
            return JsonResponse({'Exception': str(e),
                    "Line number" : str(exc_tb.tb_lineno)})

            
    
def send_mail( mail_dict, parameter, access_token):
        try:
            print("------mail send--------")
            
            if parameter['shared_mail_box']:
                # endpoint = f"https://graph.microsoft.com/v1.0/users/{self.parameter['shared_mail_id']}/sendMail"
                endpoint = f"https://graph.microsoft.com/v1.0/users/{parameter['shared_mail_id']}/messages/{mail_dict['message_id']}/replyAll"
            else:
                # endpoint = "https://graph.microsoft.com/v1.0/me/sendMail"
                endpoint = f"https://graph.microsoft.com/v1.0/me/messages/{mail_dict['message_id']}/replyAll"

            headers = {"Authorization": access_token,"Content-Type": "application/json"}
            
            body = {
            "comment": mail_dict['content']
            }

            response = requests.post(endpoint,headers=headers,data=json.dumps(body))
            print("mail send response--",response)
            if response.status_code != 202:
                print("mail send response--",response.content)
                raise Exception(json.loads(response.content))
            else:
                return {"status": True}
        
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print({'Exception': str(e),
                    "Line number" : str(exc_tb.tb_lineno)})
            
            return JsonResponse({'Exception': str(e),
                    "Line number" : str(exc_tb.tb_lineno)})

           
            