# run cinc-client bootstrap
resource "aws_imagebuilder_component" "esri_cinc_bootstrap" {
  name        = "arcgisenteprise-esri-cinc-bootstrap"
  description = "Installs Cinc and Esri Cookbooks"
  platform    = "Windows"
  data        = file("${path.module}/scripts/esri_cinc_bootstrap.yml")
  version     = var.image_version
  tags        = var.tags
}

# run cinc-client
resource "aws_imagebuilder_component" "esri_run_cinc_client" {
  name        = "arcgisenteprise-esri-run-cinc-client"
  platform    = "Windows"
  description = "Runs Cinc-Client and Esri Configurations"
  data        = file("${path.module}/scripts/esri_run_cinc_client.yml")
  version     = var.image_version
  tags        = var.tags
}

# patching
resource "aws_imagebuilder_component" "esri_patching" {
  name        = "arcgisenteprise-esri-patching"
  description = "Installs Esri Patches"
  platform    = "Windows"
  data        = file("${path.module}/scripts/esri_patching.yml")
  version     = var.image_version
  tags        = var.tags
}

### Amazon Provided Components
data "aws_imagebuilder_component" "stig_build_windows_high" {
  arn = "arn:aws:imagebuilder:${data.aws_region.current.name}:aws:component/stig-build-windows-high/x.x.x"
}

data "aws_imagebuilder_component" "amazon_cloudwatch_agent_windows" {
  arn = "arn:aws:imagebuilder:${data.aws_region.current.name}:aws:component/amazon-cloudwatch-agent-windows/x.x.x"
}

data "aws_imagebuilder_component" "windows_reboot" {
  arn = "arn:aws:imagebuilder:${data.aws_region.current.name}:aws:component/reboot-windows/x.x.x"
}
