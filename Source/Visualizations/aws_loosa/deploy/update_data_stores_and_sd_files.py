import uuid
import arcgis
import arcpy
import os
from aws_loosa.consts import egis as consts
from aws_loosa.consts import paths
import re
import boto3
import xml.dom.minidom as DOM
import sys
from pathlib import Path
from git import Repo

from aws_loosa.consts import paths
from aws_loosa.utils.viz_lambda_shared_funcs import get_service_metadata, check_s3_file_existence

s3 = boto3.resource('s3')
s3_client = boto3.client('s3')

service_dict = {
    "static_hand_catchments_0_branches_noaa": "fim_catchments",
    "static_hand_catchments_0_branches_hi_noaa": "fim_catchments",
    "static_hand_catchments_0_branches_prvi_noaa": "fim_catchments",
    "static_hand_catchments_gms_branches_noaa": "fim_catchments",
    "static_hand_catchments_gms_branches_hi_noaa": "fim_catchments",
    "static_hand_catchments_gms_branches_prvi_noaa": "fim_catchments",
    "static_nwm_flowlines": "reference",
    "static_nwm_flowlines_hi": "reference",
    "static_nwm_flowlines_prvi": "reference",
    "static_nwm_coastal_domain_noaa": "reference",
    "static_nwm_waterbodies": "reference",
    "static_nwm_waterbodies_hi": "reference",
    "static_nwm_waterbodies_prvi": "reference",
    "static_public_fim_domain": "reference",
    "static_hand_inundation_performance_metrics_noaa": "reference",
    "static_flow_based_catfim_noaa": "reference",
    "static_stage_based_catfim_noaa": "reference",
    "static_nwm_aep_inundation_extent_library_noaa": "aep_fim",
    "static_hand_rating_curve_performance_metrics_noaa": "reference",
    "static_ras2fim_boundaries_noaa": "reference"
}


def update_data_stores():
    print(f"Connecting to {consts.EGIS_HOST}")
    gis = arcgis.gis.GIS(
        f"https://{consts.EGIS_HOST}/portal", username=consts.EGIS_USERNAME, password=consts.EGIS_PASSWORD,
        verify_cert=False
    )

    print(f"Creating connection string for {os.environ['EGIS_DB_HOST']}")
    conn_str = arcpy.management.CreateDatabaseConnectionString(
        "POSTGRESQL", os.environ['EGIS_DB_HOST'], username=os.environ['EGIS_DB_USERNAME'],
        password=os.environ['EGIS_DB_PASSWORD'], database=os.environ['EGIS_DB_DATABASE']
    )
    conn_str = re.findall("<WorkspaceConnectionString>(.*)</WorkspaceConnectionString>", str(conn_str))[0]

    print("Connecting to servers")
    servers = gis.admin.servers.list()
    unique_name = uuid.uuid4().hex

    for server in servers:
        print(f"Checking {server.url} for datastores")
        if any(string in server.url for string in ['image', 'egis-img', 'server', 'egis-gis']):
            for dstore in server.datastores.list():
                if dstore.properties['type'] in ["folder", "egdb"]:
                    dstore.delete()
                    print(f"{dstore.properties['path']} successfully removed from {server.url}")

            server.datastores.add_folder(f"folder_{unique_name}", os.environ['PUBLISHED_ROOT'])
            print(f"{os.environ['PUBLISHED_ROOT']} Data Store successfully added to {server.url}")

            server.datastores.add_database(f"egis_db_{unique_name}", conn_str)
            print(f"{os.environ['EGIS_DB_HOST']} Data Store successfully added to {server.url}")


def create_sde_file():
    print(f"Checking if {paths.HYDROVIS_EGIS_DB_SDE} exists")
    if not os.path.exists(paths.HYDROVIS_EGIS_DB_SDE):

        print(f"Creating {paths.HYDROVIS_EGIS_DB_SDE}")
        connection_file_dir = os.path.dirname(paths.HYDROVIS_EGIS_DB_SDE)
        if not os.path.exists(connection_file_dir):
            print(f"Creating {connection_file_dir}")
            os.makedirs(connection_file_dir)

        print(f"Creating {paths.HYDROVIS_EGIS_DB_SDE}")
        arcpy.management.CreateDatabaseConnection(
            os.path.dirname(paths.HYDROVIS_EGIS_DB_SDE), os.path.basename(paths.HYDROVIS_EGIS_DB_SDE),
            "POSTGRESQL",  os.environ['EGIS_DB_HOST'], database=os.environ['EGIS_DB_DATABASE'],
            username=os.environ['EGIS_DB_USERNAME'], password=os.environ['EGIS_DB_PASSWORD']
        )


def update_db_sd_files(latest_deployed_github_repo_commit):  
    print("Updating mapx files and creating SD files")
    sd_folder = os.path.join(paths.AUTHORITATIVE_ROOT, "sd_files")
    deployment_bucket = os.environ['DEPLOYMENT_DATA_BUCKET']
    fim_output_bucket = os.environ['FIM_OUTPUT_BUCKET']

    print("Creating connection string to DB")
    conn_str = arcpy.management.CreateDatabaseConnectionString(
        "POSTGRESQL", os.environ['EGIS_DB_HOST'], username=os.environ['EGIS_DB_USERNAME'],
        password=os.environ['EGIS_DB_PASSWORD'], database=os.environ['EGIS_DB_DATABASE']
    )
    conn_str = re.findall("<WorkspaceConnectionString>(.*)</WorkspaceConnectionString>", str(conn_str))[0]

    if not os.path.exists(sd_folder):
        os.makedirs(sd_folder)

    baseline_aprx_path = os.path.join(paths.EMPTY_PRO_PROJECT_DIR, "Empty_Project.aprx")

    services_data = get_service_metadata()

    print(f"Getting changed services since commit {latest_deployed_github_repo_commit}")
    changed_services = []
    repo = Repo(paths.HYDROVIS_DIR)
    diffs = repo.head.commit.diff(latest_deployed_github_repo_commit)
    for d in diffs:
        changed_file = Path(d.a_path)
        file_basename = changed_file.name.split(".")[0]
        if (".mapx" in changed_file.name or ".yml" in changed_file.name) and "viz_publish_service" in str(changed_file):
            if file_basename not in changed_services:
                changed_services.append(file_basename)
        
    for service_name in changed_services:
        print(f"Creating SD file for {service_name}...")
        
        service_data = [item for item in services_data if item['service'] == service_name]
        if not service_data:
            print(f"*************\nMetadata not found for {service_name}\n*************")
            continue

        service_data = service_data[0]
        temp_aprx = arcpy.mp.ArcGISProject(baseline_aprx_path)
        temp_aprx.importDocument(service_data['mapx'])
        temp_aprx_fpath = os.path.join(sd_folder, f'{service_name}.aprx')
        temp_aprx.saveACopy(temp_aprx_fpath)
        aprx = arcpy.mp.ArcGISProject(temp_aprx_fpath)
        
        sd_file = create_sd_file(aprx, service_name, sd_folder, conn_str, service_data)
        if not sd_file:
            continue

        del temp_aprx
        del aprx
        os.remove(temp_aprx_fpath)

        print(f"Uploading {sd_file} to {deployment_bucket}")
        s3_client.upload_file(
           sd_file, deployment_bucket,
           f"viz_sd_files/{os.path.basename(sd_file)}",
           ExtraArgs={"ServerSideEncryption": "aws:kms"}
        )

        print(f"Deleting publish flag for {service_name}")
        publish_folder = service_data['egis_folder']
        publish_server = service_data['egis_server']
        publish_flag = f"published_flags/{publish_server}/{publish_folder}/{service_name}/{service_name}"
        if check_s3_file_existence(fim_output_bucket, publish_flag):
            s3_client.delete_object(Bucket=fim_output_bucket, Key=publish_flag)

def create_sd_file(aprx, service_name, sd_folder, conn_str, service_data):
    sd_service_name = f"{service_name}{consts.SERVICE_NAME_TAG}"
    sd_creation_folder = "C:\\Users\\arcgis\\sd_creation"
    sd_creation_file = os.path.join(sd_creation_folder, service_name)

    if not os.path.exists(sd_creation_folder):
        os.makedirs(sd_creation_folder)

    if os.path.exists(sd_creation_file):
        print(f"SD file already created for {service_name}")
        return

    if service_dict.get(service_name):
        schema = service_dict.get(service_name)
    else:
        schema = "services"

    m = aprx.listMaps()[0]

    print('Updating the connectionProperties of each layer...')
    for layer in m.listLayers():
        try:
            if not layer.connectionProperties:
                continue
        except:
            print(f"Skipping layer: {layer} - does not support connectionProperties")
            continue

        layerCIM = layer.getDefinition('V2')

        if layer.isRasterLayer:
            current_s3_workspace = layerCIM.dataConnection.workspaceConnectionString
            new_s3_workspace = f"DATABASE={paths.HYDROVIS_S3_CONNECTION_FILE_PATH}{current_s3_workspace.split('acs')[1]}"
            layerCIM.dataConnection.workspaceConnectionString = new_s3_workspace
        else:
            new_query = f"select * from hydrovis.{schema}.{service_name}"
            try:
                query = layerCIM.featureTable.dataConnection.sqlQuery.lower()
                if " from " not in query:
                    raise Exception("No current valid query")
                else:
                    db_source = query.split(" from ")[-1]
                    table_name = db_source.split(".")[-1]
                    new_db_source = f"hydrovis.{schema}.{table_name}"
                    new_query = query.replace(db_source, new_db_source)
            except Exception as e:
                print(f"no existing query - {e}")

            layerCIM.featureTable.dataConnection.sqlQuery = new_query

            old_dataset = layerCIM.featureTable.dataConnection.dataset
            alias = old_dataset.split(".")[-1]
            new_dataset = f"hydrovis.{schema}.{alias}"
            layerCIM.featureTable.dataConnection.dataset = new_dataset

            layerCIM.featureTable.dataConnection.workspaceConnectionString = conn_str

            try:
                delattr(layerCIM.featureTable.dataConnection, 'queryFields')
            except Exception:
                print("No querFields to delete")

        layer.setDefinition(layerCIM)

    print('Updating the connectionProperties of each table...')
    for table in m.listTables():
        if not table.connectionProperties:
            continue

        tableCIM = table.getDefinition('V2')

        new_query = f"select * from hydrovis.{schema}.{service_name}"
        try:
            query = tableCIM.dataConnection.sqlQuery.lower()
            if " from " not in query:
                raise Exception("No current valid query")
            else:
                db_source = query.split(" from ")[-1]
                table_name = db_source.split(".")[-1]
                new_db_source = f"hydrovis.{schema}.{table_name}"
                new_query = query.replace(db_source, new_db_source)
        except Exception as e:
            print(f"no existing query - {e}")

        tableCIM.dataConnection.sqlQuery = new_query

        old_dataset = tableCIM.dataConnection.dataset
        alias = old_dataset.split(".")[-1]
        new_dataset = f"hydrovis.{schema}.{alias}"
        tableCIM.dataConnection.dataset = new_dataset

        tableCIM.dataConnection.workspaceConnectionString = conn_str

        try:
            delattr(tableCIM.dataConnection, 'queryFields')
        except Exception:
            print("No querFields to delete")

        table.setDefinition(tableCIM)

    aprx.save()

    m = aprx.listMaps()[0]

    experimental_addition = """
        <br><br>The NWS is accepting comments through December 31, 2022 on the Experimental NWC Visualization Services. 
        This service is one of many Experimental NWC Visualization Services. 
        Please provide feedback on the Experimental NWC Visualization Services at: https://www.surveymonkey.com/r/Exp_NWCVisSvcs_2022
        <br><br>Link to graphical web page: https://www.weather.gov/owp/operations
        <br><br>Link to data download (shapefile): TBD
        <br><br>Link to metadata: https://nws.weather.gov/products/PDD/SDD_ExpNWCVisualizationServices_2022.pdf
    """
    
    description = service_data['description']
    if service_data['public_service']:
        description = description + experimental_addition

    summary = service_data['summary'] + consts.SUMMARY_TAG
    
    # Create MapImageSharingDraft and set service properties
    print(f"Creating MapImageSharingDraft and setting service properties for {sd_service_name}...")
    sharing_draft = m.getWebLayerSharingDraft("FEDERATED_SERVER", "MAP_IMAGE", sd_service_name)
    sharing_draft.copyDataToServer = False
    sharing_draft.overwriteExistingService = True
    sharing_draft.serverFolder = service_data['egis_folder']
    sharing_draft.summary = summary
    sharing_draft.tags = service_data['tags']
    sharing_draft.description = description
    sharing_draft.credits = service_data['credits']
    sharing_draft.serviceName = sd_service_name
    sharing_draft.offline = True

    sddraft_filename = service_name + ".sddraft"
    sddraft_output_filename = os.path.join(sd_folder, sddraft_filename)
    if os.path.exists(sddraft_output_filename):
        os.remove(sddraft_output_filename)

    print(f"Exporting MapImageSharingDraft to SDDraft file at {sddraft_output_filename}...")
    sharing_draft.exportToSDDraft(sddraft_output_filename)

    # Read the sddraft xml.
    doc = DOM.parse(sddraft_output_filename)

    typeNames = doc.getElementsByTagName('TypeName')
    for typeName in typeNames:
        if typeName.firstChild.data == "MapServer":
            extension = typeName.parentNode
            definition = extension.getElementsByTagName("Definition")[0]
            props = definition.getElementsByTagName("Props")[0]
            property_sets = props.getElementsByTagName("PropertySetProperty")
            for prop in property_sets:
                key = prop.childNodes[0].childNodes[0].data
                if key == "MinInstances":
                    prop.childNodes[1].childNodes[0].data = 1
                    
                if key == "MaxInstances":
                    prop.childNodes[1].childNodes[0].data = 5
        
        if typeName.firstChild.data == "WMSServer" and service_data['public_service']:
            extension = typeName.parentNode
            extension.getElementsByTagName("Enabled")[0].firstChild.data = "true"
            
        if typeName.firstChild.data == "FeatureServer" and service_data['feature_service']:
            extension = typeName.parentNode
            extension.getElementsByTagName("Enabled")[0].firstChild.data = "true"
            
            info = extension.getElementsByTagName("Info")[0]
            property_sets = info.getElementsByTagName("PropertySetProperty")
            for prop in property_sets:
                key = prop.childNodes[0].childNodes[0].data
                if key == "WebCapabilities":
                    prop.childNodes[1].childNodes[0].data = "Query"
                    
                if key == "allowGeometryUpdates":
                    prop.childNodes[1].childNodes[0].data = "false"  
        
        if typeName.firstChild.data == "WFSServer" and service_data['feature_service'] and (service_data['public_service'] or 'coastal' in service_name):
            extension = typeName.parentNode
            extension.getElementsByTagName("Enabled")[0].firstChild.data = "true"

    # Output to a new sddraft.
    splitext = os.path.splitext(sddraft_output_filename)
    sddraft_mod_xml_file = splitext[0] + "_mod" + splitext[1]
    f = open(sddraft_mod_xml_file, 'w')
    doc.writexml(f)
    f.close()

    sddraft_output_filename = sddraft_mod_xml_file

    sd_filename = service_name + ".sd"
    sd_output_filename = os.path.join(sd_folder, sd_filename)
    if os.path.exists(sd_output_filename):
        os.remove(sd_output_filename)
    try:
        arcpy.StageService_server(sddraft_output_filename, sd_output_filename)
    except Exception as e:
        print(e)
        return

    file2 = open(sd_creation_file,"w+")
    file2.close()

    os.remove(sddraft_output_filename)

    return sd_output_filename


if __name__ == '__main__':
    latest_deployed_github_repo_commit = sys.argv[1]
    
    update_data_stores()

    create_sde_file()

    update_db_sd_files(latest_deployed_github_repo_commit)
