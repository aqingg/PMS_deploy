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
                              const url = `https://cccn.apac.bosch.com/APP-PMS-Project/#/edit?projectId=${item.id}`;
                              // const url = `http://localhost:3001/WZE6SZH/APP-PMS-Project/#/edit?projectId=${item.id}`;
                              window.open(url, "_blank");
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
