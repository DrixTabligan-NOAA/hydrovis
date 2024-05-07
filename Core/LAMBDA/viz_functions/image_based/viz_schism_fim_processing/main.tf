variable "environment" {
  type = string
}

variable "account_id" {
  type = string
}

variable "region" {
  type = string
}

variable "ecr_repository_image_tag" {
  type = string
  default = "latest"
}

variable "codebuild_role" {
  type = string
}

variable "security_groups" {
  type = list(string)
}

variable "subnets" {
  type = list(string)
}

variable "deployment_bucket" {
  type = string
}

variable "profile_name" {
  type = string
}

variable "viz_db_name" {
  type = string
}

variable "viz_db_host" {
  type = string
}

variable "viz_db_user_secret_string" {
  type = string
}

locals {
  viz_schism_fim_resource_name = "hv-vpp-${var.environment}-viz-schism-fim-processing"
}


##################################
## SCHISM HUC PROCESSING LAMBDA ##
##################################

data "archive_file" "schism_processing_zip" {
  type = "zip"
  output_path = "${path.module}/temp/viz_schism_fim_processing.zip"

  dynamic "source" {
    for_each = fileset("${path.module}/viz_schism_fim_processing", "**")
    content {
      content  = file("${path.module}/viz_schism_fim_processing/${source.key}")
      filename = source.key
    }
  }

  source {
    content  = file("${path.module}/../../Core/LAMBDA/layers/viz_lambda_shared_funcs/python/viz_classes.py")
    filename = "viz_classes.py"
  }
}

resource "aws_s3_object" "schism_processing_zip_upload" {
  bucket      = var.deployment_bucket
  key         = "terraform_artifacts/${path.module}/viz_schism_fim_processing.zip"
  source      = data.archive_file.schism_processing_zip.output_path
  source_hash = data.archive_file.schism_processing_zip.output_md5
}

resource "aws_ecr_repository" "viz_schism_fim_processing_image" {
  name                 = local.viz_schism_fim_resource_name
  image_tag_mutability = "MUTABLE"

  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_codebuild_project" "build_schism_fim_image" {
  name          = local.viz_schism_fim_resource_name
  description   = "Codebuild project that builds the lambda container based on a zip file with lambda code and dockerfile. Also deploys a lambda function using the ECR image"
  build_timeout = "60"
  service_role  = var.codebuild_role

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type                        = "ARM_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.region
    }

    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = var.account_id
    }

    environment_variable {
      name  = "IMAGE_REPO_NAME"
      value = aws_ecr_repository.viz_schism_fim_processing_image.name
    }

    environment_variable {
      name  = "IMAGE_TAG"
      value = var.ecr_repository_image_tag
    }
  }

  source {
    type            = "S3"
    location        = "${aws_s3_object.schism_processing_zip_upload.bucket}/${aws_s3_object.schism_processing_zip_upload.key}"
  }
}

resource "null_resource" "viz_schism_fim_processing_cluster" {
  # Changes to any instance of the cluster requires re-provisioning
  triggers = {
    source_hash = data.archive_file.schism_processing_zip.output_md5
  }

  depends_on = [ aws_s3_object.schism_processing_zip_upload ]

  provisioner "local-exec" {
    command = "aws codebuild start-build --project-name ${aws_codebuild_project.build_schism_fim_image.name} --profile ${var.profile_name} --region ${var.region}"
  }
}

resource "time_sleep" "wait_for_viz_schism_fim_processing_cluster" {
  triggers = {
    function_update = null_resource.viz_schism_fim_processing_cluster.triggers.source_hash
  }
  depends_on = [null_resource.viz_schism_fim_processing_cluster]

  create_duration = "120s"
}

resource "aws_batch_compute_environment" "schism_fim_compute_env" {
  compute_environment_name = "hv-vpp-${var.environment}-schism-fim-compute-env"

  compute_resources {
    instance_role = "arn:aws:iam::526904826677:instance-profile/vpp-schism-execution-role"

    instance_type = [
      "c7g",
    ]

    min_vcpus = 0
    max_vcpus = 96

    security_group_ids = var.security_groups

    subnets = var.subnets

    type = "EC2"
  }

  service_role = "arn:aws:iam::${var.account_id}:role/aws-service-role/batch.amazonaws.com/AWSServiceRoleForBatch"
  type         = "MANAGED"
  depends_on   = [aws_iam_role_policy_attachment.aws_batch_service_role]  # Not sure on this...
}

resource "aws_batch_job_queue" "schism_fim_job_queue" {
  name     = "hv-vpp-${var.environment}-schism-fim-job-queue"
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.schism_fim_compute_env.arn
  }
}

resource "aws_batch_job_definition" "schism_fim_job_definition" {
  name = "hv-vpp-${var.environment}-schism-fim-job-definition"
  type = "container"
  container_properties = jsonencode({
    command = ["python3", "./process_schism_fim.py", "Ref::args_as_json"],
    image   = "${var.account_id}.dkr.ecr.us-east-1.amazonaws.com/${local.viz_schism_fim_resource_name}:${var.ecr_repository_image_tag}"

    resourceRequirements = [
      {
        type  = "VCPU"
        value = "4"
      },
      {
        type  = "MEMORY"
        value = "8000"
      }
    ]

    environment = [
      {
        name  = "INPUTS_BUCKET"
        value = var.deployment_bucket
      },
      {
        name  = "INPUTS_PREFIX"
        value = "schism_fim"
      },
      {
        name  = "VIZ_DB_DATABASE"
        value = var.viz_db_name
      },
      {
        name  = "VIZ_DB_HOST"
        value = var.viz_db_host
      },
      {
        name  = "VIZ_DB_PASSWORD"
        value = jsondecode(var.viz_db_user_secret_string)["password"]
      },
      {
        name  = "VIZ_DB_USERNAME"
        value = jsondecode(var.viz_db_user_secret_string)["username"]
      }
    ]
  })
}

output "job_definion" {
    value = aws_batch_job_definition.schism_fim_job_definition
}

output "job_queue" {
    value = aws_batch_job_queue.schism_fim_job_queue
}