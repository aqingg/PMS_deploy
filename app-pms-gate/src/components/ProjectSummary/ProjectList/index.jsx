import React, { useContext, useState, useEffect } from "react";
import {
  FloatButton,
  Modal,
  Form,
  Input,
  Button,
  Select
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import {
  DragDropContext,
  Droppable,
  Draggable
} from "react-beautiful-dnd";

import "./index.css";
import ProjectItem from "./ProjectItem";
import { AppContext } from "../../../context/AppContext";

export default function ProjectList({ searchText }) {
  const {
    projects,
    departments,
    createProject,
    updateProject,
    deleteProject,
    reorderProjects,
  } = useContext(AppContext);

  const [showAdd, setShowAdd] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [editForm] = Form.useForm();

  // 填充编辑表单
  useEffect(() => {
    if (editingItem) {
      editForm.setFieldsValue({
        projectName: editingItem.projectName,
        tags: editingItem.tags?.join(", "),
        comment: editingItem.comment || ""
      });
    }
  }, [editingItem, editForm]);

  // 搜索过滤
  const filteredProjects = projects.filter((item) => {
    if (!searchText) return true;

    const search = searchText.toLowerCase();

    return (
      item.projectName.toLowerCase().includes(search) ||
      (item.comment || "").toLowerCase().includes(search) ||
      (item.tags || []).join(",").toLowerCase().includes(search)
    );
  });

  // 拖拽排序
  const handleDragEnd = (result) => {
    if (!result.destination) return;

    const reordered = Array.from(projects);
    const [removed] = reordered.splice(result.source.index, 1);
    reordered.splice(result.destination.index, 0, removed);

    reorderProjects(reordered);
  };

  const normalizeTags = (tags) => {
    if (!tags) return [];

    if (Array.isArray(tags)) {
      return tags;
    }

    if (typeof tags === "string") {
      return tags
        .split(",")
        .map(t => t.trim())
        .filter(Boolean);
    }

    return [];
  };

  /*
   * oss_eng_hub prevents a child tool's index.html from being opened as a
   * top-level page. Therefore:
   *
   * 1. Open the normal APP-PMS-Project route in the Hub.
   * 2. Wait for the Hub to create iframe.tool-frame.
   * 3. Set the iframe URL to the Project application's own edit route,
   *    including the selected projectId.
   *
   * The new Hub window and the Gate iframe are on the same origin, so the
   * Gate can access the new window's document. Do not add "noopener" here,
   * because this function must retain the opened-window reference.
   */
  const openProjectInHub = (rawProjectId) => {
    const projectId = Number(rawProjectId);

    if (!Number.isInteger(projectId) || projectId <= 0) {
      Modal.error({
        title: "Unable to open project",
        content: `Invalid project ID: ${String(rawProjectId)}`
      });
      return;
    }

    /*
     * Temporary bootstrap fallback:
     * before the iframe URL is replaced, APP-PMS-Project may initialize once
     * without a URL projectId and read localStorage. The final iframe URL still
     * remains the authoritative project source.
     */
    localStorage.setItem("projectId", String(projectId));

    const hubUrl =
      `${window.location.origin}/oss_eng_hub/#/APP-PMS-Project`;

    const projectWindow = window.open(hubUrl, "_blank");

    if (!projectWindow) {
      Modal.error({
        title: "Unable to open project",
        content: "The browser blocked the new project window. Please allow pop-ups for this site."
      });
      return;
    }

    const projectIframeUrl =
      `${window.location.origin}` +
      `/oss_eng_hub/APP-PMS-Project/index.html` +
      `#/edit?projectId=${encodeURIComponent(projectId)}`;

    const startedAt = Date.now();
    const timeoutMs = 15000;
    const pollIntervalMs = 100;

    const timer = window.setInterval(() => {
      if (projectWindow.closed) {
        window.clearInterval(timer);
        return;
      }

      if (Date.now() - startedAt > timeoutMs) {
        window.clearInterval(timer);

        Modal.error({
          title: "Unable to open project",
          content: "Timed out while waiting for APP-PMS-Project to load in the Hub."
        });
        return;
      }

      try {
        const iframe =
          projectWindow.document.querySelector("iframe.tool-frame");

        if (!iframe) {
          return;
        }

        /*
         * At this point APP-PMS-Project runs inside an iframe, so the Hub's
         * top-level redirect guard is not triggered.
         */
        iframe.setAttribute("src", projectIframeUrl);
        window.clearInterval(timer);
      } catch (error) {
        /*
         * During navigation or authentication initialization, the new
         * document may be temporarily unavailable. Continue polling until the
         * timeout is reached.
         */
      }
    }, pollIntervalMs);
  };

  return (
    <div className="project-table-container">
      <div className="project-table-wrapper">

        {/* ⭐ 你的原始表头（不修改） */}
        <div className="project-table-header">
          <div className="project-header-row">
            <div className="col project-col-rate">Progress</div>
            <div className="col project-col-title">Project</div>
            <div className="col project-col-comment">My Comment</div>
            <div className="col project-col-tag">Tags</div>
          </div>
        </div>

        <DragDropContext onDragEnd={handleDragEnd}>
          <Droppable droppableId="projectList">
            {(provided) => (
              <div ref={provided.innerRef} {...provided.droppableProps}>
                {filteredProjects.map((item, index) => (
                  <Draggable
                    key={item.id}
                    draggableId={String(item.id)}
                    index={index}
                  >
                    {(pp) => (
                      <div
                        ref={pp.innerRef}
                        {...pp.draggableProps}
                        {...pp.dragHandleProps}
                      >
                        <ProjectItem
                          value={item}
                          onAction={(action) => {
                            if (action === "editProject") {
                              setEditingItem(item);
                              setShowEdit(true);
                            }

                            if (action === "deleteProject") {
                              deleteProject(item.id);
                            }

                            if (action === "openProject") {
                              openProjectInHub(item.id);
                            }
                          }}
                        />
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>

        {/* 浮动按钮 */}
        <div className="project-float-buttons">
          <FloatButton
            icon={<PlusOutlined />}
            type="default"
            tooltip="New Project"
            onClick={() => setShowAdd(true)}
          />
        </div>
      </div>

      {/* 新建项目弹窗 */}
      <Modal
        title="New Project"
        open={showAdd}
        onCancel={() => setShowAdd(false)}
        footer={null}
      >
        <Form
          layout="vertical"
          onFinish={(values) => {
            const payload = {
              ...values,
              tags: normalizeTags(values.tags),
            };

            createProject(payload);
            setShowAdd(false);
          }}
        >
          <Form.Item name="projectName" label="Project Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          <Form.Item name="department" label="Department" rules={[{ required: true }]}>
            <Select>
              {departments.map((d) => (
                <Select.Option key={d} value={d}>
                  {d}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item name="tags" label="Tags (comma separated)">
            <Input />
          </Form.Item>

          <Form.Item name="comment" label="Comment">
            <Input.TextArea rows={3} />
          </Form.Item>

          <Button type="primary" htmlType="submit" block>
            Create
          </Button>
        </Form>
      </Modal>

      {/* 编辑项目弹窗 */}
      <Modal
        title="Edit Project"
        open={showEdit}
        onCancel={() => {
          setShowEdit(false);
          setEditingItem(null);
        }}
        footer={null}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            updateProject(editingItem.id, values);
            setShowEdit(false);
          }}
        >
          <Form.Item name="projectName" label="Project Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          <Form.Item name="tags" label="Tags (comma separated)">
            <Input />
          </Form.Item>

          <Form.Item name="comment" label="Comment">
            <Input.TextArea rows={3} />
          </Form.Item>

          <Button type="primary" htmlType="submit" block>
            Save Changes
          </Button>
        </Form>
      </Modal>
    </div>
  );
}
