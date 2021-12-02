/**
 * Copyright 2021 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
*/

resource "google_sql_database_instance" "instance" {
  depends_on          = [var.nat_ips]
  name                = var.sql_instance_name
  region              = var.region
  deletion_protection = var.deletion_protection

  settings {
    tier = var.tier
    ip_configuration {

      ipv4_enabled = true

      dynamic "authorized_networks" {
        for_each = var.nat_ips
        iterator = ip

        content {
          name  = ip.value
          value = "${ip.value}/32"
        }
      }
    }
  }
}

resource "google_sql_database" "database" {
  name     = "slurm_accounting"
  instance = google_sql_database_instance.instance.name
}

resource "google_sql_user" "users" {
  name     = "slurm"
  instance = google_sql_database_instance.instance.name
  password = "verysecure"
}

resource "google_bigquery_connection" "connection" {
  provider      = google-beta
  project       = var.project_id
  friendly_name = "👋"
  cloud_sql {
    instance_id = google_sql_database_instance.instance.connection_name
    database    = google_sql_database.database.name
    type        = "MYSQL"
    credential {
      username = google_sql_user.users.name
      password = google_sql_user.users.password
    }
  }
}
