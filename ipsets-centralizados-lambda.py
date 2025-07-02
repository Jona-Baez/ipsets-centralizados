import boto3
import time

start = time.time()

# Relación entre nombre de IPSet y nombre del archivo S3
IPSETS_CONFIG = {
    "blacklist": "blacklist.txt",
    "whitelist": "whitelist.txt"
}

# Nombre del bucket
BUCKET_NAME = 'ipsets-centralizados-bucket'

# Cuentas destino
DESTINATION_ACCOUNTS = [
    {
        "name": "Cuenta A",
        "account_id": "XXXXXXXXXXXX",  # Reemplaza con la cuenta A
        "region": "us-east-1"
    },
    {
        "name": "Cuenta B",
        "account_id": "YYYYYYYYYYYY",  # Reemplaza con la cuenta B
        "region": "eu-west-1"
    }
]

# Nombre del rol a asumir en cada cuenta
ROLE_NAME = 'ipsets-centralizados-update'

def lambda_handler(event, context):
    s3 = boto3.client('s3')

    for ipset_name, filename in IPSETS_CONFIG.items():
        print(f"📦 Leyendo objeto {filename} desde S3...")
        try:
            obj = s3.get_object(Bucket=BUCKET_NAME, Key=filename)
            ip_list_raw = obj['Body'].read().decode('utf-8').splitlines()
            ip_addresses = [ip.strip() for ip in ip_list_raw if ip.strip()]
        except Exception as e:
            print(f"❌ Error al leer {filename}: {str(e)}")
            continue

        for account in DESTINATION_ACCOUNTS:
            for scope in ['REGIONAL', 'CLOUDFRONT']:
                region = account['region'] if scope == 'REGIONAL' else 'us-east-1'
                print(f"➡️ {account['name']} | Scope: {scope} | Región: {region} | IPSet: {ipset_name}")
                try:
                    waf_client = assume_role_and_get_waf_client(account['account_id'], region, ipset_name)
                    update_ipset(waf_client, ip_addresses, scope, ipset_name)
                except Exception as e:
                    print(f"❌ Error al procesar {account['name']} - {scope} - {ipset_name}: {str(e)}")

    print(f"✅ Proceso finalizado en {time.time() - start:.2f} segundos.")

def assume_role_and_get_waf_client(account_id, region, ipset_name):
    sts = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{ROLE_NAME}'
    session_name = f'UpdateSession-{ipset_name[:10]}'

    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name
    )
    creds = response['Credentials']

    session = boto3.Session(
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
        region_name=region
    )
    return session.client('wafv2')

def update_ipset(waf_client, ip_addresses, scope, ipset_name):
    response = waf_client.list_ip_sets(Scope=scope)
    ipset = next((i for i in response['IPSets'] if i['Name'] == ipset_name), None)
    if not ipset:
        raise Exception(f"IPSet '{ipset_name}' no encontrado en {scope}")

    ipset_detail = waf_client.get_ip_set(Name=ipset_name, Scope=scope, Id=ipset['Id'])
    current_addresses = ipset_detail['IPSet']['Addresses']
    lock_token = ipset_detail['LockToken']

    if sorted(current_addresses) != sorted(ip_addresses):
        waf_client.update_ip_set(
            Name=ipset_name,
            Scope=scope,
            Id=ipset['Id'],
            Addresses=ip_addresses,
            LockToken=lock_token
        )
        print(f"✅ IPSet '{ipset_name}' actualizado con {len(ip_addresses)} IPs en {scope}")
    else:
        print(f"🟡 IPSet '{ipset_name}' ya estaba actualizado en {scope}")
