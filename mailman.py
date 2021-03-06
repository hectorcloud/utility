#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
upload|download file by sending|receiving email

fully tested under Python 2.x for upload and 3.x for download

Date: 2016-03-21
"""
import os
import re
import sys
import hashlib
import datetime
import tarfile
import time
import shutil
import subprocess
import threading
import multiprocessing
import mimetypes
import getpass
import smtplib
import imaplib
import email
from email.utils import formataddr
from email.utils import parseaddr
from email.utils import formatdate
from email.utils import COMMASPACE
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.audio import MIMEAudio
from email.mime.multipart import MIMEMultipart
import email.header
from email import encoders
from email.parser import HeaderParser


# email accounts
sender = {
    # https://www.google.com/settings/security/lesssecureapps, please 'turn on'
    'Email': '***@gmail.com',
    'SMTP': 'smtp.gmail.com',
    'IMAP': 'imap.gmail.com',
    'Password': '***',
}
receiver = {
    # http://stackoverflow.com/questions/27797705/python-login-163-mail-server
    'Email': '***@163.com',
    'SMTP': 'smtp.163.com',
    'IMAP': 'imap.163.com',
    'Password': '***'
}


if sys.version[0] == '2':
    global input
    input = raw_input
    global range
    range = xrange


# attachment size is 25M
chunksize = 25*1024*1024
# reserve memory to avoid out-of-memory
BUFFER = bytearray(chunksize)
# parallel download
dw_thread_number = 3
dw_lock = threading.Lock()
# how many bytes to download?
dw_total_size = 0

# on Windows 'mbcs' means 'utf-8'
sysencode = sys.getfilesystemencoding()
isWindows = sys.platform.startswith("win")
if isWindows and sysencode == 'mbcs':
    sysencode = 'utf-8'


# obfuscate bytearray data stream
def obfuscatebytes(data):
    # XOR with 1010-0101
    for i in range(len(data)):
        data[i] ^= 0xA5
    return


def obfuscatefile(filename):
    buffer = bytearray(chunksize)
    fd = open(filename, "rb")
    length = fd.readinto(buffer)
    fd.close()
    obfuscatebytes(buffer)
    fd = open(filename, "wb")
    fd.write(memoryview(buffer)[:length])
    fd.close()
    print(b"codec file: " + filename.encode())
    return

def files2send(_dir):
    """
    collecting what files to send by mail
    :param _dir: directory or file to upload
    :return: list of tar files
    """
    # list all files in directory
    files2upload = []
    # unfinished of last round
    files2delete = []
    # archive might be done last round, in that case,
    # there is no need to do archive operation this round
    for root, dirs, files in os.walk(_dir):
        for _file in files:
            _file = os.path.join(root, _file)
            # exclude unfinished chunk file last time
            if re.search(r"\.\d{6}$", _file):
                files2delete.append(_file)
                continue
            # exclude hidden dirs and files
            if r"/." in _file or r"\." in _file:
                continue
            # add to upload list
            files2upload.append(os.path.abspath(_file))
    # delete unwanted files
    for _file in files2delete:
        os.remove(_file)

    # change working directory
    workdir = None
    abspath = os.path.abspath(_dir)
    if os.path.isfile(abspath):
        workdir = os.path.dirname(abspath)
    else:
        workdir = abspath
    os.chdir(workdir)

    files2upload = [os.path.relpath(_file, workdir) for _file in files2upload]
    files2upload.sort(key=os.path.getsize)
    # archive each file then delete it
    # each file will be archived separately.
    # Benefit is to preserve non-ascii file|dir name in archive.
    # archive itself is named by its SHA1 whose characters are ascii.
    # not all into a single file due to file size limit in OS
    #
    # April 06, 2016
    # archive small files together because gmail has restriction on mail sending
    # numbers within a period.
    files2upload_final = []
    group = []
    for idx, _file in enumerate(files2upload, start=0):
        _base = os.path.basename(_file)
        # already archived such as last round upload
        if not re.search(r"[^0-9a-fA-F]", _base):
            # SHA1 of this file
            sha1 = hashlib.sha1()
            with open(_file, "rb") as fd:
                for chunk in iter(lambda: fd.read(1*1024*1024), b''):
                    sha1.update(chunk)
            tarname = sha1.hexdigest()
            # confirm
            if tarname == _base:
                # move to top level in order to handle non-ascii character in file|dir name
                os.rename(_file, tarname)
                # files2upload[idx] = tarname
                files2upload_final.append(tarname)
                continue
        group_size = sum([os.path.getsize(x) for x in group])
        if group_size + os.path.getsize(_file) < chunksize:
            group.append(_file)
            continue
        if group:
            # archive of last round not finished yet
            sha1 = hashlib.sha1()
            # sha1 of first file name in group as temporary name
            if sys.version[0] == '2':
                sha1.update(group[0])
            else:
                sha1.update(group[0].encode(sysencode, 'surrogateescape'))
            tmpname = sha1.hexdigest()
            tar = tarfile.open(tmpname, "w")
            for f in group:
                tar.add(f)
                os.remove(f)
            tar.close()
            # sha1 of file content as file name
            sha1 = hashlib.sha1()
            with open(tmpname, "rb") as fd:
                for chunk in iter(lambda: fd.read(1*1024*1024), b''):
                    sha1.update(chunk)
            tarname = sha1.hexdigest()
            # at top level
            os.rename(tmpname, tarname)
            # files2upload[idx] = tarname
            files2upload_final.append(tarname)
        # new group, next round
        #group.clear()
        del group[:]
        group.append(_file)
    else:
        if group:
            # archive of last round not finished yet
            sha1 = hashlib.sha1()
            # sha1 of first file name in group as temporary name
            if sys.version[0] == '2':
                sha1.update(group[0])
            else:
                sha1.update(group[0].encode(sysencode, 'surrogateescape'))
            tmpname = sha1.hexdigest()
            tar = tarfile.open(tmpname, "w")
            for f in group:
                tar.add(f)
                os.remove(f)
            tar.close()
            # sha1 of file content as file name
            sha1 = hashlib.sha1()
            with open(tmpname, "rb") as fd:
                for chunk in iter(lambda: fd.read(1*1024*1024), b''):
                    sha1.update(chunk)
            tarname = sha1.hexdigest()
            # at top level
            os.rename(tmpname, tarname)
            # files2upload[idx] = tarname
            files2upload_final.append(tarname)
    # absolute path recovery
    files2upload_final = [os.path.join(workdir, _file) for _file in files2upload_final]
    files2upload_final.sort()

    return files2upload_final


def sendByEmail(subjectPrefix, _file):
    """
    send file as attachment chunk by chunk
    email subject is: [subjectPrefix]<file.000000>
    :param subjectPrefix:
    :param _file:
    :return:
    """
    # name is as <file.000000>; content is octet stream
    def sendByChunk(name, content):
        # start to upload
        print("upload start [{prefix}/{chunk}]".format(prefix=subjectPrefix, chunk=name))

        # Create the enclosing (outer) message
        outer = MIMEMultipart()
        outer['From'] = formataddr(("Mr. Alpha", sender['Email']))
        outer['To'] = COMMASPACE.join([receiver['Email']])
        outer['Subject'] = Header('[{subjectPrefix}]{fn}'.format(subjectPrefix=subjectPrefix, fn=name), 'utf-8').encode()
        outer['Date'] = formatdate(localtime=1)
        outer.preamble = 'You will not see this in a MIME-aware mail reader.\n'
        html = """
            <!DOCTYPE html>
            <html>
              <head><title></title></head>
              <body>
                <p>
                {name}
                </p>
              </body>
            </html>
            """.format(name=name)
        text = MIMEText(html, "html")
        outer.attach(text)
        msg = MIMEBase('application', 'octet-stream')
        msg.set_payload(content)
        encoders.encode_base64(msg)
        msg.add_header('Content-Disposition', 'attachment', filename=Header(name, 'utf-8').encode())
        outer.attach(msg)

        # login
        smtpGmail = smtplib.SMTP_SSL(host=sender['SMTP'], port=465)
        smtpGmail.ehlo()
        try:
            # port=587
            smtpGmail.starttls()
            smtpGmail.ehlo()
        except smtplib.SMTPException as e:
            pass
            # print(e)
        username = sender['Email']
        smtpGmail.login(username, sender['Password'])
        # send message
        if sys.version[0] == '2':
            smtpGmail.sendmail(sender['Email'], outer['To'], outer.as_string())        
        if sys.version[0] == '3':
            smtpGmail.send_message(outer)
        smtpGmail.quit()
        # successful
        print("upload finished [{prefix}/{chunk}]".format(prefix=subjectPrefix, chunk=name))

    size = os.path.getsize(_file)
    for idx in range((size + chunksize - 1) // chunksize):
        chunk = os.path.basename(_file) + "." + str(idx).zfill(6)
        length = None
        with open(_file, "rb") as fd:
            fd.seek(idx*chunksize, 0)
            length = fd.readinto(BUFFER)
            mv = memoryview(BUFFER)
            # why not 'mv' here?
            obfuscatebytes(BUFFER)            
        # try until success
        ctr = 0
        while True:
            try:
                mv = memoryview(BUFFER)
                sendByChunk(chunk, mv[:length])
            # smtplib.SMTPServerDisconnected
            # smtplib.SMTPSenderRefused
            except Exception as e:
                ctr += 1
                print(e)
                print('try again after {t} seconds'.format(t=str(ctr*60)))
                time.sleep(ctr * 60)
            else:
                break


def upload():
    """
    upload files chunk by chunk whose size is 'chunksize'.
    delete mails in 'Sent Mail' folder at first, they are left by last upload
    :return:
    """
    uploadDir = input("directory|file to upload: ")
    subjectPrefix = input("mail subject prefix: ")

    # working directory may change later
    uploadDir = os.path.abspath(uploadDir)

    # delete all mails in 'Sent Mail' folder
    # avoid to excess quota
    _delete_sent_mail()

    time_started = datetime.datetime.now()

    # absolute path
    files2upload = files2send(uploadDir)
    # upload each file by email
    for _file in files2upload:
        sendByEmail(subjectPrefix, _file)
    # size of all uploaded files
    total_size = 0
    for _file in files2upload:
        total_size += os.path.getsize(_file)

    time_finished = datetime.datetime.now()
    time_spend = time_finished - time_started
    upload_speed = 0
    if time_spend.total_seconds() > 0:
        upload_speed = total_size // (time_spend.total_seconds()*1024)
    print("start: " + time_started.strftime("%Y-%m-%d %H:%M:%S"))
    print("finished: " + time_finished.strftime("%Y-%m-%d %H:%M:%S"))
    print("transfer size: " + str(total_size) + " bytes")
    print("spent: " + str(time_spend))
    print("speed: " + str(upload_speed) + " kps")
    
    # KiwiVM has some disadvantages. It's related to system buff/cache.
    # delete directory|files which were uploaded.
    # I don't know how to resolved it by other means except deletion.
    # http://stackoverflow.com/questions/3797958/how-to-write-script-output-to-file-and-command-line
    if total_size > 0:
        # delete directory|files which were uploaded
        # http://stackoverflow.com/questions/11025784/calling-rm-from-subprocess-using-wildcards-does-not-remove-the-files
        # file and directory to delete
        files_to_delete = []
        if os.path.isdir(uploadDir):
            for f in os.listdir(uploadDir):
                if f.startswith("."):
                    continue
                files_to_delete.append(os.path.abspath(f))
        else:
            files_to_delete.append(uploadDir)
        # delete file and directory one by one
        for f in files_to_delete:
            if os.path.isfile(f):
                os.remove(f)
            else:
                shutil.rmtree(f)


def subjects_inbox():
    """
    get all subject prefix in 'Inbox' of mail @163.com
    :return:
    """
    # mail subjects
    subjects = []

    M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
    # M.debug = 7
    M.login(receiver['Email'], receiver['Password'])

    # mail folders
    t = M.list()
    # print(t)

    mb = 'INBOX'
    rv, data = M.select(mailbox=M._quote(mb))
    if rv == 'OK':
        rv, data = M.uid('search', None, "ALL")
        if rv != 'OK':
            print("there is no message in {mb}".format(mb=mb))
            return
        uids = data[0]
        for uid in uids.split():
            rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
            if rv != 'OK':
                # Fetch volume limit exceed.
                # Please try next day
                print("ERROR getting message {uid}: {rv} {_data}".format(uid=str(uid), rv=rv, _data=_data))
                continue
            header_data = _data[0][1].decode('utf-8')
            parser = HeaderParser()
            msg = parser.parsestr(header_data)
            hdr = email.header.decode_header(msg['Subject'])
            _subject = hdr[0][0] if type(hdr[0][0]) == type('str') else hdr[0][0].decode(hdr[0][1])
            print(('{mb}: ' + _subject).format(mb=mb).encode())
            subjects.append(_subject)
        M.close()
    else:
        print("ERROR: unable to open {mb}. ".format(mb=mb) + rv)
    M.logout()

    return subjects


def merge_chunks(_dir):
    # list all files in directory
    file2merge = []
    for root, dirs, files in os.walk(_dir):
        for _file in files:
            _file = os.path.join(root, _file)
            file2merge.append(_file)
    file2merge.sort()
    # recover file name by strip '.000001' ending
    filenames = [fn[:-7] for fn in file2merge if re.match(r"\.\d{6}", fn[-7:])]
    filenames = set(filenames)
    filenames = list(filenames)
    filenames.sort()

    # integrity check. Are all files downloaded? Are their size is equal except last one?
    # do NOT use 'chunksize' anymore because it's always changing.
    for fn in filenames:
        chunks = []
        for chunk in file2merge:
            if (fn == chunk[:-7]) and re.match(r"\.\d{6}", chunk[-7:]):
                chunks.append(chunk)
        # each chunk is of same size except last one for each file
        # cardinality is continuous
        chunks.sort()
        sizes = set()
        for idx in range(len(chunks)-1):
            chunk = chunks[idx]
            if int(chunk[-6:]) != idx:
                suffix = "." + str(idx).zfill(6)
                print("error: {} not exists".format(chunk[:-7] + suffix))
                exit(1)
            sizes.add(os.path.getsize(chunk))
        # all except last one equal?
        if len(sizes) > 1:
            print("error: chunks of file[{fn}] not equal(already excluded last one)".format(fn=fn))
            exit(1)
        # last chunk
        idx = len(chunks) - 1
        chunk = chunks[idx]
        if int(chunk[-6:]) != idx:
            suffix = "." + str(idx).zfill(6)
            print("error: {} not exists".format(chunk[:-7] + suffix))
            exit(1)

    # decrypt file content. reuse mutex of downloading thread
    """
    def decryptFile(filelist):
        buffer = bytearray(chunksize)
        while True:
            filename = None
            dw_lock.acquire()
            if len(filelist) > 0:
                filename = filelist.pop(0)
                print(b"decrypt file: " + filename.encode())
            dw_lock.release()
            if filename is None:
                return
            fd = open(filename, "rb")
            length = fd.readinto(buffer)
            fd.close()
            obfuscatebytes(buffer)
            fd = open(filename, "wb")
            fd.write(memoryview(buffer)[:length])
            fd.close()
    file2merge_copy = [filename for filename in file2merge if re.match(r"\.\d{6}", filename[-7:])]
    file2merge_copy.sort()
    # parallel decryption
    decrypt_threads = []
    for i in range(dw_thread_number):
        t = threading.Thread(target=decryptFile, args=(file2merge_copy,))
        t.start()
        decrypt_threads.append(t)
    for t in decrypt_threads:
        t.join()
    """

    file2merge_copy = [filename for filename in file2merge if re.match(r"\.\d{6}", filename[-7:])]
    file2merge_copy.sort()
    """
    # parallel decryption
    with multiprocessing.Pool(dw_thread_number) as pool:
        pool.map(obfuscatefile, file2merge_copy)
    """

    # merge chunk files
    os.chdir(_dir)
    for fn in filenames:
        print("info: merge file {}".format(fn))
        for chunk in file2merge:
            if (fn == chunk[:-7]) and re.match(r"\.\d{6}", chunk[-7:]):
                with open(chunk, "rb") as fd:
                    data = fd.read()
                    with open(fn, "ab") as _fd:
                        _fd.write(data)
                # remove chunk file due to merged
                os.remove(chunk)
        # integrity check by SHA1
        # file name is SHA1
        filename = os.path.basename(fn)
        sha1 = hashlib.sha1()
        with open(fn, 'rb') as fd:
            for chunk in iter(lambda: fd.read(1*1024*1024), b''):
                sha1.update(chunk)
        sha1 = sha1.hexdigest()
        if filename != sha1:
            print("{fn} fails SHA1 integrity check".format(fn=fn))
        # extract tar
        tar = tarfile.open(fn, "r")
        tar.extractall()
        tar.close()
        os.remove(fn)


def download_by_subject(subject_list):
    """
    download from email@163.com based on subject.
    This is running inside thread.
    """
    # loop until there is nothing to download
    while True:
        subject = None
        dw_lock.acquire()
        if len(subject_list) > 0:
            subject = subject_list.pop()
        dw_lock.release()
        if subject is None:
            return

        M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
        # M.debug = 7 #debug
        M.login(receiver['Email'], receiver['Password'])
        rv, data = M.select(mailbox='INBOX')
        if rv == 'OK':
            rv, data = M.uid('search', None, 'ALL')
            if rv != 'OK':
                print("there is no message in INBOX")
                continue
            uids = data[0]
            for uid in uids.split():
                # whether downloaded or not?
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv != 'OK':
                    # Fetch volume limit exceed. Please try next day
                    print("ERROR getting message {uid}: {rv} {_data}".format(uid=str(uid), rv=rv, _data=_data))
                    continue
                header_data = _data[0][1].decode('utf-8')
                parser = HeaderParser()
                msg = parser.parsestr(header_data)
                hdr = email.header.decode_header(msg['Subject'])
                _subject = hdr[0][0].decode(hdr[0][1])
                # subject match exactly
                if _subject != subject:
                    continue                    
                # subject pattern
                res = re.search(r'\[(.*)\](.*\.(\d{6}))$', _subject)
                if not res:
                    continue

                # already downloaded
                # algorithm: (1) file exists; (2) size equals chunksize
                # traits: not perfect but useful
                _prefix = res.group(1)
                filename = res.group(2)
                if os.path.exists(filename):
                    if os.path.getsize(filename) == chunksize:
                        print("downloaded before: [{_prefix}]{filename}".format(_prefix=_prefix, filename=filename))
                        continue

                rv, _data = M.uid('fetch', uid, '(RFC822)')
                if rv != 'OK':
                    print("ERROR getting message {uid}".format(uid=str(uid)))
                    continue
                mail = None
                if sys.version[0] == '2':
                    mail = email.message_from_string(_data[0][1])
                if sys.version[0] == '3':
                    mail = email.message_from_bytes(_data[0][1])
                # hdr = email.header.decode_header(mail['Subject'])
                # _subject = hdr[0][0].decode(hdr[0][1])
                # if not _subject.startswith('[' + _prefix + ']'):
                #     continue
                for part in mail.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    if part.get('Content-Disposition') is None:
                        continue
                    filename = part.get_filename()
                    # decode filename
                    t = email.header.decode_header(filename)
                    filename = t[0][0].decode(t[0][1])
                    if filename:
                        fp = open(filename, 'wb')
                        # data is of type bytes
                        data = part.get_payload(decode=True)
                        data = bytearray(data)
                        obfuscatebytes(data)
                        fp.write(data)
                        fp.close()
                        dw_lock.acquire()
                        global dw_total_size
                        dw_total_size += len(data)
                        print("download finished: [{_prefix}]{filename}".format(_prefix=_prefix, filename=filename))
                        dw_lock.release()
            M.close()
        else:
            print("ERROR: unable to open INBOX. " + rv)
        M.logout()


def download():
    """
    download from email@163.com
    1. list what to download, let user choose
    2. download attachment of emails contain the prefix. decryption is done when saving.
    3. delete mails in INBOX
    4. merge each chunk
    :return:
    """
    time_started = datetime.datetime.now()
    # traffic quota
    print("traffic quota for email@163.com is around 3 GiB every day.")
    cwd = os.getcwd()

    subjects = subjects_inbox()
    prefixes = []
    subjects_of_same_prefix = {}
    
    # advertisement mail
    ads = []
    for _subject in subjects:
        res = re.search(r'\[(.*)\].*\.(\d{6})$', _subject)
        if res:
            prefix = res.group(1)
            prefixes.append(prefix)
            if prefix not in subjects_of_same_prefix:
                subjects_of_same_prefix[prefix] = []
            subjects_of_same_prefix[prefix].append(_subject)
        else:
            ads.append(_subject)
            
    # delete advertisement mail
    for ad in ads:
        _delete_inbox_mail2(ad)
        
    prefixes = list(set(prefixes))
    prefixes.sort()
    
    for _prefix in prefixes:
        _dir = os.path.join(cwd, _prefix)
        if os.path.isfile(_dir):
            print("cannot create [{_dir}] because a file has the same name".format(_dir=_prefix))
            exit()
        if not os.path.exists(_dir):
            os.mkdir(_dir)

        # change working directory
        os.chdir(_dir)
        
        # parallel downloading
        dw_threads = []
        subject_list = subjects_of_same_prefix[prefix]
        subject_list = list(set(subject_list))
        for i in range(dw_thread_number):
            t = threading.Thread(target=download_by_subject, args=(subject_list,))
            t.start()
            dw_threads.append(t)
        for t in dw_threads:
            t.join()
        """
        M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
        # M.debug = 7 #debug
        M.login(receiver['Email'], receiver['Password'])
        rv, data = M.select(mailbox='INBOX')
        if rv == 'OK':
            rv, data = M.uid('search', None, 'ALL')
            if rv != 'OK':
                print("there is no message in INBOX")
                continue
            uids = data[0]
            for uid in uids.split():
                # whether downloaded or not?
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv != 'OK':
                    # Fetch volume limit exceed. Please try next day
                    print("ERROR getting message {uid}: {rv} {_data}".format(uid=str(uid), rv=rv, _data=_data))
                    continue
                header_data = _data[0][1].decode('utf-8')
                parser = HeaderParser()
                msg = parser.parsestr(header_data)
                hdr = email.header.decode_header(msg['Subject'])
                _subject = hdr[0][0].decode(hdr[0][1])
                # subject pattern: phase 1
                if not _subject.startswith('[' + _prefix + ']'):
                    continue
                # subject pattern: phase 2
                res = re.search(r'\[(.*)\](.*\.(\d{6}))$', _subject)
                if not res:
                    continue
                # already downloaded
                # algorithm: (1) file exists; (2) size equals chunksize
                # traits: not perfect but useful
                filename = res.group(2)
                if os.path.exists(filename):
                    if os.path.getsize(filename) == chunksize:
                        print("downloaded before: [{_prefix}]{filename}".format(_prefix=_prefix, filename=filename))
                        continue

                rv, _data = M.uid('fetch', uid, '(RFC822)')
                if rv != 'OK':
                    print("ERROR getting message {uid}".format(uid=str(uid)))
                    continue
                mail = None
                if sys.version[0] == '2':
                    mail = email.message_from_string(_data[0][1])
                if sys.version[0] == '3':
                    mail = email.message_from_bytes(_data[0][1])
                # hdr = email.header.decode_header(mail['Subject'])
                # _subject = hdr[0][0].decode(hdr[0][1])
                # if not _subject.startswith('[' + _prefix + ']'):
                #     continue
                for part in mail.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    if part.get('Content-Disposition') is None:
                        continue
                    filename = part.get_filename()
                    # decode filename
                    t = email.header.decode_header(filename)
                    filename = t[0][0].decode(t[0][1])
                    if filename:
                        fp = open(filename, 'wb')
                        # data is of type bytes
                        data = part.get_payload(decode=True)
                        for idx, d in enumerate(data):
                            BUFFER[idx] = d
                        data = memoryview(BUFFER)[:len(data)]
                        obfuscatebytes(data)
                        fp.write(data)
                        fp.close()
                        total_size += len(data)
                        print("download finished: [{_prefix}]{filename}".format(_prefix=_prefix, filename=filename))
            M.close()
        else:
            print("ERROR: unable to open INBOX. " + rv)
        M.logout()
        """

        # merge chunks, MUST before mail deletion to guarantee download is finished.
        M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
        M.login(receiver['Email'], receiver['Password'])
        rv, data = M.select(mailbox='INBOX')
        if rv == 'OK':
            rv, data = M.uid('search', None, "ALL")
            if rv == 'OK':
                uids = data[0]
                uid = uids.split()[0]
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv == 'OK':
                    merge_chunks(_dir)

        # delete mail in INBOX
        _delete_inbox_mail(_prefix)

    time_finished = datetime.datetime.now()
    time_spend = time_finished - time_started
    download_speed = dw_total_size // (time_spend.total_seconds()*1024)
    print("start: " + time_started.strftime("%Y-%m-%d %H:%M:%S"))
    print("finished: " + time_finished.strftime("%Y-%m-%d %H:%M:%S"))
    print("transfer size: " + str(dw_total_size) + " bytes")
    print("spent: " + str(time_spend))
    print("speed: " + str(download_speed) + " kps")


def _delete_inbox_mail(_prefix):
    """
    delete INBOX @163.com if its prefix is '[prefix]'
    :param prefix: subject prefix
    :return:
    """
    for mb in ['INBOX']:
        M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
        M.login(receiver['Email'], receiver['Password'])
        rv, data = M.select(mailbox=mb)
        if rv == 'OK':
            rv, data = M.uid('search', None, "ALL")
            if rv != 'OK':
                print("there is no message in {mb}".format(mb=mb))
                return
            uids = data[0]
            uid2delete = []
            for uid in uids.split():
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv != 'OK':
                    print("ERROR getting message {uid}: {rv}".format(uid=str(uid), rv=rv))
                    continue
                header_data = _data[0][1].decode('utf-8')
                parser = HeaderParser()
                msg = parser.parsestr(header_data)
                hdr = email.header.decode_header(msg['Subject'])
                _subject = hdr[0][0] if type(hdr[0][0]) == type('str') else hdr[0][0].decode(hdr[0][1])
                if not _subject.startswith('[' + _prefix + ']'):
                    continue
                uid2delete.append((uid.decode(), _subject))
            for _uid, _subject in uid2delete:
                print("delete {_uid}: {_subject}".format(_uid=_uid, _subject=_subject))
                M.uid('store', _uid, '+FLAGS', '(\\Deleted)')
            M.expunge()
            M.close()
        else:
            print("ERROR: unable to open {mb}. {rv}".format(mb=mb, rv=rv))
        M.logout()


def _delete_inbox_mail2(_subject):
    """
    delete INBOX @163.com based on mail subject
    :param _subject: mail subject
    :return:
    """
    for mb in ['INBOX']:
        M = imaplib.IMAP4_SSL(receiver['IMAP'], 993)
        M.login(receiver['Email'], receiver['Password'])
        rv, data = M.select(mailbox=mb)
        if rv == 'OK':
            rv, data = M.uid('search', None, "ALL")
            if rv != 'OK':
                print("there is no message in {mb}".format(mb=mb))
                return
            uids = data[0]
            uid2delete = []
            for uid in uids.split():
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv != 'OK':
                    print("ERROR getting message {uid}: {rv}".format(uid=str(uid), rv=rv))
                    continue
                header_data = _data[0][1].decode('utf-8')
                parser = HeaderParser()
                msg = parser.parsestr(header_data)
                hdr = email.header.decode_header(msg['Subject'])
                subject = hdr[0][0] if type(hdr[0][0]) == type('str') else hdr[0][0].decode(hdr[0][1])
                if subject != _subject:
                    continue
                uid2delete.append((uid.decode(), subject))
            for _uid, subject in uid2delete:
                print("delete {_uid}: {subject}".format(_uid=_uid, subject=subject).encode())
                M.uid('store', _uid, '+FLAGS', '(\\Deleted)')
            M.expunge()
            M.close()
        else:
            print("ERROR: unable to open {mb}. {rv}".format(mb=mb, rv=rv))
        M.logout()
        
        
def _delete_sent_mail():
    """
    delete sent mails @gmail.com
    Gmail keeps a copy in 'Sent Mail' folder for each mail sent.
    delete mails in the folder
    :return:
    """
    for mb in ['INBOX', '[Gmail]/All Mail', '[Gmail]/Sent Mail', '[Gmail]/Spam', '[Gmail]/Trash']:
        M = imaplib.IMAP4_SSL(sender['IMAP'], 993)
        username = sender['Email']
        M.login(username, sender['Password'])
        rv, data = M.select(mailbox=M._quote(mb))
        if rv == 'OK':
            rv, data = M.uid('search', None, "ALL")
            if rv != 'OK':
                print("there is no message in '{mb}'".format(mb=mb))
                return
            uids = data[0]
            uid2delete = []
            for uid in uids.split():
                rv, _data = M.uid('fetch', uid, '(BODY.PEEK[HEADER])')
                if rv != 'OK':
                    print("ERROR getting message {uid}: {rv}".format(uid=str(uid), rv=rv))
                    continue
                # avoid decode error
                try:
                    header_data = _data[0][1].decode('utf-8')
                    parser = HeaderParser()
                    msg = parser.parsestr(header_data)
                    hdr = email.header.decode_header(msg['Subject'])
                    _subject = hdr[0][0].decode(hdr[0][1])
                    print("delete {mb}: {_subject}".format(mb=mb, _subject=_subject).encode())
                except Exception as e:
                    pass
                uid2delete.append(uid.decode())
            for _uid in uid2delete:
                M.uid('store', _uid, '+FLAGS', '(\\Deleted)')
            M.expunge()
            M.close()
        else:
            print('ERROR: unable to open "{mb}". '.format(mb=mb) + rv)
        M.logout()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        usage = """{script} upload\n{script} download\n""".format(
            script=os.path.basename(sys.argv[0])
        )
        print(usage)
        exit(0)
    action = sys.argv[1]
    if action == 'upload':
        upload()
    elif action == 'download':
        download()
    else:
        print("not supported argument")

